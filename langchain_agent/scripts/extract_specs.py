#!/usr/bin/env python3
"""
Extract component SPEC definitions from Lucille Java source files.

Walks the Lucille source tree, finds all classes with `public static final Spec SPEC`,
parses the SpecBuilder chain to extract property definitions, and outputs a
component_catalog.json used by the config builder for deterministic spec resolution.

Usage:
    python scripts/extract_specs.py [--lucille-root ../lucille] [--output data/component_catalog.json]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# SpecBuilder default properties per builder type
BUILDER_DEFAULTS = {
    "stage": [
        {"name": "name", "type": "String", "required": False, "is_parent": False},
        {"name": "class", "type": "String", "required": False, "is_parent": False},
        {"name": "conditions", "type": "List", "required": False, "is_parent": False},
        {"name": "conditionPolicy", "type": "String", "required": False, "is_parent": False},
    ],
    "connector": [
        {"name": "name", "type": "String", "required": False, "is_parent": False},
        {"name": "class", "type": "String", "required": False, "is_parent": False},
        {"name": "pipeline", "type": "String", "required": False, "is_parent": False},
        {"name": "docIdPrefix", "type": "String", "required": False, "is_parent": False},
        {"name": "collapse", "type": "Boolean", "required": False, "is_parent": False},
    ],
    "indexer": [],
    "fileHandler": [
        {"name": "class", "type": "String", "required": False, "is_parent": False},
        {"name": "docIdPrefix", "type": "String", "required": False, "is_parent": False},
    ],
    "parent": [],
}


def find_java_files_with_spec(lucille_root: Path) -> List[Path]:
    """Find all Java source files (excluding tests) containing SPEC definitions."""
    spec_files = []
    search_dirs = [
        lucille_root / "lucille-core" / "src" / "main" / "java",
    ]

    # Add plugin source dirs
    plugins_dir = lucille_root / "lucille-plugins"
    if plugins_dir.exists():
        for plugin in plugins_dir.iterdir():
            src_dir = plugin / "src" / "main" / "java"
            if src_dir.exists():
                search_dirs.append(src_dir)

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for java_file in search_dir.rglob("*.java"):
            # Skip test files
            if "/test/" in str(java_file):
                continue
            try:
                content = java_file.read_text(encoding="utf-8")
                if "public static final Spec SPEC = SpecBuilder" in content:
                    spec_files.append(java_file)
            except (OSError, UnicodeDecodeError):
                continue

    return spec_files


def derive_class_info(java_file: Path, lucille_root: Path) -> Dict:
    """Derive class name, package, component type from file path."""
    rel = java_file.relative_to(lucille_root)
    parts = rel.parts

    # Find 'java' directory to start package path
    try:
        java_idx = parts.index("java")
        package_parts = parts[java_idx + 1:]
    except ValueError:
        package_parts = parts

    # Class name from file
    short_name = java_file.stem
    class_path = "/".join(package_parts)
    if class_path.endswith(".java"):
        class_path = class_path[:-5]
    class_name = class_path.replace("/", ".")
    package = ".".join(class_path.split("/")[:-1])

    # Component type from path
    path_str = str(java_file).lower()
    if "/indexer/" in path_str:
        component_type = "indexer"
    elif "/connector/" in path_str:
        component_type = "connector"
    elif "/stage/" in path_str:
        component_type = "stage"
    elif "/filehandler/" in path_str or "filehandler" in short_name.lower():
        component_type = "fileHandler"
    else:
        component_type = "other"

    # Source file relative to lucille root
    source_file = str(rel)

    return {
        "class_name": class_name,
        "short_name": short_name,
        "component_type": component_type,
        "package": package,
        "source_file": source_file,
    }


def extract_spec_block(content: str) -> Optional[str]:
    """Extract the SPEC = SpecBuilder...build() block from Java source."""
    # Find the start of the SPEC definition
    match = re.search(
        r'public\s+static\s+final\s+Spec\s+SPEC\s*=\s*SpecBuilder\.',
        content,
    )
    if not match:
        return None

    start = match.start()

    # Find matching .build() — need to handle nested SpecBuilder.parent().build()
    # Strategy: find the .build(); that ends the top-level SPEC assignment
    text = content[start:]

    # Count nesting depth of SpecBuilder calls
    depth = 0
    i = 0
    while i < len(text):
        if text[i:].startswith("SpecBuilder."):
            depth += 1
            i += len("SpecBuilder.")
        elif text[i:].startswith(".build()"):
            depth -= 1
            if depth <= 0:
                return text[: i + len(".build()")]
            i += len(".build()")
        else:
            i += 1

    # Fallback: find the first .build(); after SPEC
    build_match = re.search(r'\.build\(\)\s*;', text)
    if build_match:
        return text[: build_match.end()]

    return None


def extract_builder_type(spec_block: str) -> str:
    """Extract the builder type from SpecBuilder.stage(), .connector(), etc."""
    match = re.search(r'SpecBuilder\.(\w+)\(\)', spec_block)
    if match:
        return match.group(1)
    return "unknown"


def extract_quoted_strings(text: str) -> List[str]:
    """Extract all double-quoted strings from text."""
    return re.findall(r'"([^"]*)"', text)


def extract_type_reference(text: str) -> str:
    """Extract type from TypeReference<...>."""
    match = re.search(r'TypeReference<([^>]+)>', text)
    if match:
        return match.group(1).strip()
    return "Object"


def parse_spec_chain(spec_block: str) -> List[Dict]:
    """Parse SpecBuilder method chain into parameter definitions."""
    parameters = []
    seen_names = set()

    # Remove the initial SpecBuilder.xxx() call
    chain = re.sub(r'SpecBuilder\.\w+\(\)\s*', '', spec_block, count=1)

    # Pattern for method calls: .methodName(args)
    # We need to handle nested parentheses for SpecBuilder.parent() calls
    methods = _split_method_chain(chain)

    for method_name, args_text in methods:
        params = _parse_method_call(method_name, args_text)
        for p in params:
            if p["name"] not in seen_names:
                parameters.append(p)
                seen_names.add(p["name"])

    return parameters


def _split_method_chain(chain: str) -> List[Tuple[str, str]]:
    """Split a method chain into (method_name, args) pairs, handling nested parens."""
    methods = []
    i = 0
    text = chain.strip()

    while i < len(text):
        # Find next .methodName(
        match = re.search(r'\.(\w+)\(', text[i:])
        if not match:
            break

        method_name = match.group(1)
        args_start = i + match.end()

        # Skip internal SpecBuilder methods like build()
        if method_name == "build":
            i = args_start + 1  # skip past build()
            continue

        # Find matching closing paren
        depth = 1
        j = args_start
        while j < len(text) and depth > 0:
            if text[j] == '(':
                depth += 1
            elif text[j] == ')':
                depth -= 1
            j += 1

        args_text = text[args_start:j - 1]
        methods.append((method_name, args_text))
        i = j

    return methods


def _parse_method_call(method_name: str, args_text: str) -> List[Dict]:
    """Parse a single SpecBuilder method call into parameter definitions."""
    params = []

    # Determine required/optional and type from method name
    is_required = method_name.startswith("required")
    is_with_desc = "WithDescription" in method_name

    # Determine property type category
    method_lower = method_name.lower()
    if "string" in method_lower:
        prop_type = "String"
        is_parent = False
    elif "boolean" in method_lower:
        prop_type = "Boolean"
        is_parent = False
    elif "number" in method_lower:
        prop_type = "Number"
        is_parent = False
    elif "list" in method_lower:
        prop_type = "List"
        is_parent = False
    elif "parent" in method_lower:
        prop_type = "Object"
        is_parent = True
    elif "properties" in method_lower:
        # withRequiredProperties / withOptionalProperties
        prop_type = "Any"
        is_parent = False
        is_required = "required" in method_lower.replace("with", "")
    elif method_name == "include":
        # .include(spec) — skip, this merges another spec
        return []
    else:
        return []

    # Handle WithDescription variants: (name, description) or (spec, description)
    if is_with_desc and is_parent:
        # requiredParentWithDescription(Spec, "desc") or (name, TypeRef, "desc")
        description = _extract_last_quoted_string(args_text)
        # Try to get parent name from spec or first arg
        name = _extract_parent_name_from_args(args_text)
        if name:
            params.append({
                "name": name,
                "type": prop_type,
                "required": is_required,
                "is_parent": True,
                "description": description or "",
            })
        return params
    elif is_with_desc:
        # requiredStringWithDescription("name", "desc")
        strings = extract_quoted_strings(args_text)
        if len(strings) >= 2:
            params.append({
                "name": strings[0],
                "type": prop_type,
                "required": is_required,
                "is_parent": False,
                "description": strings[1],
            })
        return params

    # Handle Parent methods
    if is_parent:
        parent_params = _parse_parent_args(args_text, is_required)
        params.extend(parent_params)
        return params

    # Handle List methods: requiredList("name", TypeReference<...>) or ("name", Spec)
    if "list" in method_lower:
        strings = extract_quoted_strings(args_text)
        if strings:
            type_ref = extract_type_reference(args_text)
            list_type = f"List[{type_ref}]" if type_ref != "Object" else "List"
            params.append({
                "name": strings[0],
                "type": list_type,
                "required": is_required,
                "is_parent": False,
                "description": "",
            })
        return params

    # Handle simple type methods: requiredString("a", "b", "c")
    strings = extract_quoted_strings(args_text)
    for name in strings:
        params.append({
            "name": name,
            "type": prop_type,
            "required": is_required,
            "is_parent": False,
            "description": "",
        })

    return params


def _extract_last_quoted_string(text: str) -> Optional[str]:
    """Extract the last quoted string from args (usually the description)."""
    strings = extract_quoted_strings(text)
    return strings[-1] if strings else None


def _extract_parent_name_from_args(args_text: str) -> Optional[str]:
    """Extract parent name from parent method args."""
    # Check for SpecBuilder.parent("name")
    match = re.search(r'SpecBuilder\.parent\("(\w+)"\)', args_text)
    if match:
        return match.group(1)
    # Check for first quoted string (name arg)
    strings = extract_quoted_strings(args_text)
    if strings:
        return strings[0]
    # Check for external spec constant reference (e.g., OpenSearchUtils.OPENSEARCH_PARENT_SPEC)
    match = re.search(r'(\w+)\.(\w+_PARENT_SPEC)', args_text)
    if match:
        # Try to derive a name from the constant
        const = match.group(2)
        name = const.replace("_PARENT_SPEC", "").lower()
        return name
    # Check for local constant reference (e.g., GCP_PARENT_SPEC)
    match = re.search(r'(\w+_PARENT_SPEC)', args_text)
    if match:
        const = match.group(1)
        name = const.replace("_PARENT_SPEC", "").lower()
        return name
    return None


def _parse_parent_args(args_text: str, is_required: bool) -> List[Dict]:
    """Parse parent method arguments into parameters."""
    params = []

    # Case 1: optionalParent("name", TypeReference<...>)
    strings = extract_quoted_strings(args_text)
    type_ref_match = re.search(r'TypeReference<([^>]+)>', args_text)

    if strings and type_ref_match and not args_text.strip().startswith("SpecBuilder"):
        # Simple parent with name and type
        params.append({
            "name": strings[0],
            "type": type_ref_match.group(1).strip(),
            "required": is_required,
            "is_parent": True,
            "description": "",
        })
        return params

    # Case 2: optionalParent(SpecBuilder.parent("name")...build(), SpecBuilder.parent("name2")...build(), ...)
    # or mixed with constants like GCP_PARENT_SPEC
    # Split on top-level commas (not inside nested parens)
    top_level_args = _split_top_level_args(args_text)

    for arg in top_level_args:
        arg = arg.strip()

        # Check for SpecBuilder.parent("name")
        parent_match = re.search(r'SpecBuilder\.parent\("(\w+)"\)', arg)
        if parent_match:
            params.append({
                "name": parent_match.group(1),
                "type": "Object",
                "required": is_required,
                "is_parent": True,
                "description": "",
            })
            continue

        # Check for constant reference (e.g., GCP_PARENT_SPEC)
        const_match = re.match(r'(\w+_PARENT_SPEC)', arg)
        if const_match:
            name = const_match.group(1).replace("_PARENT_SPEC", "").lower()
            params.append({
                "name": name,
                "type": "Object",
                "required": is_required,
                "is_parent": True,
                "description": "",
            })
            continue

        # Check for ExternalClass.CONSTANT
        ext_match = re.match(r'(\w+)\.(\w+_PARENT_SPEC)', arg)
        if ext_match:
            name = ext_match.group(2).replace("_PARENT_SPEC", "").lower()
            params.append({
                "name": name,
                "type": "Object",
                "required": is_required,
                "is_parent": True,
                "description": "",
            })
            continue

        # Check for simple "name" followed by TypeReference
        if strings and not parent_match:
            name = strings[0] if strings else None
            if name and name not in [p["name"] for p in params]:
                type_ref = extract_type_reference(arg)
                params.append({
                    "name": name,
                    "type": type_ref if type_ref != "Object" else "Object",
                    "required": is_required,
                    "is_parent": True,
                    "description": "",
                })

    return params


def _split_top_level_args(text: str) -> List[str]:
    """Split args on commas that are at the top level (depth 0 for parens)."""
    args = []
    depth = 0
    current = []

    for ch in text:
        if ch in "({":
            depth += 1
            current.append(ch)
        elif ch in ")}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        args.append("".join(current))

    return args


def extract_javadoc_params(content: str, class_name: str) -> Dict[str, str]:
    """Extract parameter descriptions from Javadoc Config Parameters block."""
    descriptions = {}

    # Find the class javadoc: the comment block before the class declaration
    class_pattern = rf'(public\s+(?:abstract\s+)?class\s+{re.escape(class_name)})'
    class_match = re.search(class_pattern, content)
    if not class_match:
        return descriptions

    # Look for the javadoc comment before the class
    before_class = content[:class_match.start()]
    # Find the last /** ... */ block
    javadoc_matches = list(re.finditer(r'/\*\*(.+?)\*/', before_class, re.DOTALL))
    if not javadoc_matches:
        return descriptions

    javadoc = javadoc_matches[-1].group(1)

    # Extract <li> items from Config Parameters block
    # Pattern: paramName (Type, Optional/Required) : description
    li_pattern = re.compile(
        r'<li>\s*(\w+)\s*\(([^)]+)\)\s*[:\-]\s*(.*?)</li>',
        re.DOTALL,
    )
    for match in li_pattern.finditer(javadoc):
        param_name = match.group(1).strip()
        desc = match.group(3).strip()
        # Clean up javadoc artifacts
        desc = re.sub(r'\s*\*\s*', ' ', desc)
        desc = re.sub(r'<[^>]+>', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()
        descriptions[param_name] = desc[:300]

    return descriptions


def extract_class_description(content: str, class_name: str) -> str:
    """Extract the class-level description from Javadoc."""
    class_pattern = rf'(public\s+(?:abstract\s+)?class\s+{re.escape(class_name)})'
    class_match = re.search(class_pattern, content)
    if not class_match:
        return ""

    before_class = content[:class_match.start()]
    javadoc_matches = list(re.finditer(r'/\*\*(.+?)\*/', before_class, re.DOTALL))
    if not javadoc_matches:
        return ""

    javadoc = javadoc_matches[-1].group(1)

    # Get first paragraph (before first <p> or Config Parameters)
    # Clean javadoc comment markers
    lines = []
    for line in javadoc.split('\n'):
        line = re.sub(r'^\s*\*\s?', '', line)
        lines.append(line)
    text = ' '.join(lines).strip()

    # Take text before first <p>, @, or "Config Parameters"
    for separator in ['<p>', 'Config Parameters', '@param', '@deprecated']:
        idx = text.find(separator)
        if idx > 0:
            text = text[:idx]

    # Clean HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text[:500]


def check_deprecated(content: str, class_name: str) -> bool:
    """Check if the class has a @Deprecated annotation."""
    pattern = rf'@Deprecated\s+.*?class\s+{re.escape(class_name)}'
    return bool(re.search(pattern, content, re.DOTALL))


def process_java_file(java_file: Path, lucille_root: Path) -> Optional[Dict]:
    """Process a single Java file and extract its SPEC definition."""
    content = java_file.read_text(encoding="utf-8")

    class_info = derive_class_info(java_file, lucille_root)
    short_name = class_info["short_name"]

    # Extract the SPEC block
    spec_block = extract_spec_block(content)
    if not spec_block:
        return None

    # Get builder type
    builder_type = extract_builder_type(spec_block)

    # Parse the chain
    parameters = parse_spec_chain(spec_block)

    # Extract javadoc descriptions
    javadoc_params = extract_javadoc_params(content, short_name)
    javadoc_desc = extract_class_description(content, short_name)

    # Merge javadoc descriptions into parameters
    for param in parameters:
        if param["name"] in javadoc_params and not param.get("description"):
            param["description"] = javadoc_params[param["name"]]

    # Check deprecated
    deprecated = check_deprecated(content, short_name)

    # Get default properties for this builder type
    defaults = BUILDER_DEFAULTS.get(builder_type, [])
    default_names = [d["name"] for d in defaults]

    return {
        "class_name": class_info["class_name"],
        "short_name": short_name,
        "component_type": class_info["component_type"],
        "builder_type": builder_type,
        "description": javadoc_desc,
        "deprecated": deprecated,
        "parameters": parameters,
        "default_properties": default_names,
        "source_file": class_info["source_file"],
    }


def main():
    parser = argparse.ArgumentParser(description="Extract Lucille component SPEC definitions")
    parser.add_argument(
        "--lucille-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "lucille",
        help="Path to Lucille project root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "component_catalog.json",
        help="Output path for component catalog JSON",
    )
    args = parser.parse_args()

    lucille_root = args.lucille_root.resolve()
    output_path = args.output.resolve()

    if not lucille_root.exists():
        print(f"Error: Lucille root not found at {lucille_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {lucille_root} for SPEC definitions...")

    # Find all Java files with SPEC
    java_files = find_java_files_with_spec(lucille_root)
    print(f"Found {len(java_files)} files with SPEC definitions")

    # Process each file
    components = {}
    errors = []

    for java_file in sorted(java_files):
        try:
            result = process_java_file(java_file, lucille_root)
            if result:
                components[result["short_name"]] = result
                param_count = len(result["parameters"])
                print(f"  {result['short_name']:30s} {result['component_type']:12s} {param_count} params")
            else:
                errors.append(f"Could not extract SPEC from {java_file}")
        except Exception as e:
            errors.append(f"Error processing {java_file}: {e}")

    # Build catalog
    catalog = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(lucille_root),
        "component_count": len(components),
        "components": components,
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(catalog, f, indent=2)

    print(f"\nWrote {len(components)} components to {output_path}")

    # Summary by type
    by_type = {}
    for comp in components.values():
        t = comp["component_type"]
        by_type[t] = by_type.get(t, 0) + 1
    for t, count in sorted(by_type.items()):
        print(f"  {t}: {count}")

    if errors:
        print(f"\n{len(errors)} errors:")
        for e in errors:
            print(f"  {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
