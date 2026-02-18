"""
Structured component spec extraction for Lucille documentation.

Parses javadoc-extracted text into structured ComponentParam/ComponentSpec
dataclasses for use by the Config Builder and Documentation Writer.
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

import psycopg

from config import DATABASE_URL

logger = logging.getLogger(__name__)


@dataclass
class ComponentParam:
    """A single configuration parameter for a Lucille component."""
    name: str
    type: str = "String"
    description: str = ""
    required: bool = True
    default: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ComponentSpec:
    """Structured specification for a Lucille component (stage, connector, indexer)."""
    class_name: str  # Fully qualified, e.g. "com.kmwllc.lucille.stage.CopyFields"
    short_name: str  # Simple name, e.g. "CopyFields"
    component_type: str  # "stage", "connector", "indexer", "core", "other_api"
    description: str = ""
    parameters: List[ComponentParam] = field(default_factory=list)
    package: str = ""
    source_url: str = ""

    def to_dict(self) -> Dict:
        return {
            "class_name": self.class_name,
            "short_name": self.short_name,
            "component_type": self.component_type,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "package": self.package,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ComponentSpec":
        params = [ComponentParam(**p) for p in data.get("parameters", [])]
        return cls(
            class_name=data.get("class_name", ""),
            short_name=data.get("short_name", ""),
            component_type=data.get("component_type", ""),
            description=data.get("description", ""),
            parameters=params,
            package=data.get("package", ""),
            source_url=data.get("source_url", ""),
        )


def extract_component_spec(extracted_text: str, source_path: str) -> Optional[ComponentSpec]:
    """
    Parse already-extracted javadoc text into a structured ComponentSpec.

    Looks for patterns like:
    - "Config Parameters - fieldName (Type, Optional) : description"
    - Constructor parameters from "Parameters:" sections
    - Class description from "Class Description:" prefix

    Args:
        extracted_text: Text previously extracted from javadoc HTML
        source_path: Relative file path (e.g. "com/kmwllc/lucille/stage/CopyFields.html")

    Returns:
        ComponentSpec if extraction succeeded, None otherwise
    """
    if not extracted_text or not source_path:
        return None

    # Derive class info from path
    path_clean = source_path.replace("\\", "/")
    if path_clean.endswith(".html"):
        path_clean = path_clean[:-5]

    class_name = path_clean.replace("/", ".")
    short_name = path_clean.split("/")[-1]
    package = ".".join(path_clean.split("/")[:-1])

    # Determine component type from path
    path_lower = source_path.lower()
    if "/stage/" in path_lower:
        component_type = "stage"
    elif "/connector/" in path_lower:
        component_type = "connector"
    elif "/indexer/" in path_lower:
        component_type = "indexer"
    elif "/core/" in path_lower:
        component_type = "core"
    else:
        component_type = "other_api"

    # Extract class description
    description = ""
    desc_match = re.search(r"Class Description:\s*(.+?)(?:\n\n|$)", extracted_text, re.DOTALL)
    if desc_match:
        description = desc_match.group(1).strip()
    elif extracted_text:
        # Use first sentence as description
        first_sentence = re.match(r"[^.]*\.", extracted_text)
        if first_sentence:
            description = first_sentence.group(0).strip()

    # Extract parameters from javadoc text patterns
    parameters = []

    # Pattern 1: "fieldName (Type, Optional) : description" or "fieldName (Type) : description"
    param_pattern = re.compile(
        r"(\w+)\s*\((\w+)(?:,\s*(Optional|Required))?\)\s*:\s*(.+?)(?=\w+\s*\(|\Z)",
        re.DOTALL
    )
    for match in param_pattern.finditer(extracted_text):
        name = match.group(1)
        param_type = match.group(2)
        required_str = match.group(3)
        desc = match.group(4).strip()

        required = required_str != "Optional" if required_str else True

        # Check for default value in description
        default = None
        default_match = re.search(r"[Dd]efault[s]?(?:\s+(?:to|is|value))?\s*[:=]?\s*[\"']?(\S+)[\"']?", desc)
        if default_match:
            default = default_match.group(1).rstrip(".,;)")

        parameters.append(ComponentParam(
            name=name,
            type=param_type,
            description=desc[:200],  # Truncate long descriptions
            required=required,
            default=default,
        ))

    # Pattern 2: "Parameters: name - description" blocks from javadoc
    params_section = re.search(r"Parameters?:\s*(.+?)(?:Returns?:|Throws?:|$)", extracted_text, re.DOTALL)
    if params_section and not parameters:
        param_lines = re.findall(r"(\w+)\s*[-–:]\s*(.+?)(?=\w+\s*[-–:]|\Z)", params_section.group(1), re.DOTALL)
        for name, desc in param_lines:
            # Skip if already captured
            if any(p.name == name for p in parameters):
                continue
            parameters.append(ComponentParam(
                name=name,
                type="String",
                description=desc.strip()[:200],
            ))

    return ComponentSpec(
        class_name=class_name,
        short_name=short_name,
        component_type=component_type,
        description=description[:500],
        parameters=parameters,
        package=package,
        source_url="",
    )


def load_component_specs(component_type: Optional[str] = None) -> List[ComponentSpec]:
    """
    Load component specs from the database.

    Args:
        component_type: Filter by type ("stage", "connector", "indexer", etc.)
                       None returns all components with specs.

    Returns:
        List of ComponentSpec objects

    Raises:
        DatabaseError: If database connection or query fails
    """
    from exceptions import DatabaseError

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                if component_type:
                    cur.execute(
                        """
                        SELECT metadata FROM documents
                        WHERE collection_id = 'lucille_docs'
                          AND metadata->>'component_type' = %s
                          AND metadata->'component_spec' IS NOT NULL
                        """,
                        (component_type,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT metadata FROM documents
                        WHERE collection_id = 'lucille_docs'
                          AND metadata->'component_spec' IS NOT NULL
                        """
                    )

                specs = []
                for row in cur.fetchall():
                    metadata = row[0] if isinstance(row, tuple) else row
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except json.JSONDecodeError as e:
                            logger.error(f"Component specs: Corrupted metadata", extra={"row": str(row)[:200]})
                            continue  # Skip corrupted rows
                    spec_data = metadata.get("component_spec")
                    if spec_data:
                        specs.append(ComponentSpec.from_dict(spec_data))
                return specs

    except psycopg.OperationalError as e:
        logger.error(f"Component specs: Database connection failed", extra={"error": str(e), "component_type": component_type})
        raise DatabaseError(
            f"Unable to load component specs - database unavailable",
            operation="load_component_specs",
            table="documents",
            recoverable=True
        )
    except psycopg.Error as e:
        logger.error(f"Component specs: Database error loading specs", extra={"error": str(e), "component_type": component_type})
        raise DatabaseError(
            f"Database error while loading component specs",
            operation="load_component_specs",
            table="documents",
            recoverable=True
        )
