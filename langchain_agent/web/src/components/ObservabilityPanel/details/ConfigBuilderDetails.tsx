/**
 * Detail views for config builder observability steps.
 */

import { useObservabilityStore } from '../../../stores/observabilityStore'
import clsx from 'clsx'

export function ConfigBuilderDetails({ node }: { node: string }) {
  const { configBuilderStart, componentSpecRetrieval, configGenerated } = useObservabilityStore()

  if (node === 'config_resolver') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {/* User request */}
        {configBuilderStart && (
          <div>
            <span className="font-semibold text-gray-200">Request:</span>
            <p className="mt-1 text-gray-300">{configBuilderStart.user_request}</p>
          </div>
        )}

        {/* Pipeline description from LLM */}
        {componentSpecRetrieval?.pipeline_description && (
          <div>
            <span className="font-semibold text-gray-200">Pipeline:</span>
            <p className="mt-1 text-gray-300 italic">{componentSpecRetrieval.pipeline_description}</p>
          </div>
        )}

        {/* Per-component details */}
        {componentSpecRetrieval?.component_details && componentSpecRetrieval.component_details.length > 0 && (
          <div className="space-y-2">
            <span className="font-semibold text-gray-200">Components:</span>
            {componentSpecRetrieval.component_details.map((comp) => (
              <div
                key={comp.name}
                className={clsx(
                  'p-2 rounded-lg border',
                  comp.resolved
                    ? 'bg-green-500/10 border-green-500/30'
                    : 'bg-yellow-500/10 border-yellow-500/30'
                )}
              >
                <div className="flex items-center gap-2">
                  <span className={clsx(
                    'text-xs font-medium px-1.5 py-0.5 rounded',
                    comp.component_type === 'connector' && 'bg-blue-500/20 text-blue-300',
                    comp.component_type === 'stage' && 'bg-purple-500/20 text-purple-300',
                    comp.component_type === 'indexer' && 'bg-amber-500/20 text-amber-300',
                  )}>
                    {comp.component_type}
                  </span>
                  <span className="font-mono text-xs text-gray-200">{comp.name}</span>
                  {comp.resolved ? (
                    <span className="text-green-400 text-xs ml-auto">spec found</span>
                  ) : (
                    <span className="text-yellow-400 text-xs ml-auto">search fallback</span>
                  )}
                </div>
                {comp.class_name && (
                  <p className="mt-1 text-xs text-gray-400 font-mono truncate">{comp.class_name}</p>
                )}
                {comp.description && (
                  <p className="mt-0.5 text-xs text-gray-400">{comp.description}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Fallback: old-style found/not-found if no component_details */}
        {componentSpecRetrieval && (!componentSpecRetrieval.component_details || componentSpecRetrieval.component_details.length === 0) && (
          <div className="space-y-2">
            <span className="font-semibold text-gray-200">Component Resolution:</span>

            {componentSpecRetrieval.components_found.length > 0 && (
              <div className="p-2 rounded-lg bg-green-500/10 border border-green-500/30">
                <span className="text-green-400 text-xs font-medium">FOUND</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {componentSpecRetrieval.components_found.map((c) => (
                    <span key={c} className="px-2 py-0.5 rounded text-xs bg-green-500/20 text-green-300">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {componentSpecRetrieval.components_not_found.length > 0 && (
              <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/30">
                <span className="text-red-400 text-xs font-medium">NOT FOUND</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {componentSpecRetrieval.components_not_found.map((c) => (
                    <span key={c} className="px-2 py-0.5 rounded text-xs bg-red-500/20 text-red-300">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!configBuilderStart && !componentSpecRetrieval && (
          <div className="text-sm text-gray-400">Resolving components...</div>
        )}
      </div>
    )
  }

  if (node === 'config_generator') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {configGenerated ? (
          <>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Components:</span>
              <span className="text-amber-300">{configGenerated.component_count}</span>
            </div>

            {configGenerated.validation_notes.length > 0 && (
              <div>
                <span className="font-semibold text-gray-200">Validation Notes:</span>
                <ul className="mt-1 space-y-1">
                  {configGenerated.validation_notes.map((note, i) => (
                    <li key={i} className="text-xs text-yellow-400/80 flex items-start gap-1">
                      <span className="mt-0.5">⚠</span>
                      <span>{note}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <span className="font-semibold text-gray-200">Preview:</span>
              <pre className="mt-1 p-2 rounded bg-gray-800/50 text-xs text-gray-300 overflow-x-auto max-h-48 overflow-y-auto">
                {configGenerated.config_preview}
              </pre>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-400">Generating config...</div>
        )}
      </div>
    )
  }

  if (node === 'config_response') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        <div className={clsx(
          'flex items-center gap-2',
          configGenerated ? 'text-green-400' : 'text-gray-400'
        )}>
          <span className="font-semibold text-gray-200">Status:</span>
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-400">
            {configGenerated ? 'Formatting response' : 'Waiting for config...'}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="text-sm text-gray-500">
      No details available for this config builder step.
    </div>
  )
}
