/**
 * Detail views for documentation writer observability steps.
 */

import { useObservabilityStore } from '../../../stores/observabilityStore'

export function DocWriterDetails({ node }: { node: string }) {
  const { docOutline, docSectionProgress, docComplete } = useObservabilityStore()

  if (node === 'doc_planner') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {docOutline ? (
          <>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Components:</span>
              <span className="text-teal-300">{docOutline.total_components}</span>
            </div>

            <div>
              <span className="font-semibold text-gray-200">Outline:</span>
              <ol className="mt-1 space-y-1 list-decimal list-inside">
                {docOutline.sections.map((section, i) => (
                  <li key={i} className="text-xs text-gray-300">{section}</li>
                ))}
              </ol>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-400">Planning documentation structure...</div>
        )}
      </div>
    )
  }

  if (node === 'doc_gatherer') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {docSectionProgress ? (
          <>
            <div>
              <span className="font-semibold text-gray-200">Current Section:</span>
              <span className="ml-2 text-teal-300">{docSectionProgress.section_title}</span>
            </div>

            {/* Progress bar */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-gray-200">Progress:</span>
                <span className="text-xs text-teal-400">
                  {docSectionProgress.sections_complete}/{docSectionProgress.sections_total} sections
                </span>
              </div>
              <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-teal-500 transition-all"
                  style={{
                    width: `${docSectionProgress.sections_total > 0 ? (docSectionProgress.sections_complete / docSectionProgress.sections_total) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Components Gathered:</span>
              <span className="text-gray-300">{docSectionProgress.components_gathered}</span>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-400">Gathering documentation content...</div>
        )}
      </div>
    )
  }

  if (node === 'doc_synthesizer') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {docComplete ? (
          <>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Sections:</span>
              <span className="text-teal-300">{docComplete.total_sections}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Components Documented:</span>
              <span className="text-teal-300">{docComplete.total_components_documented}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Document Size:</span>
              <span className="text-gray-300">
                {docComplete.document_length_chars > 1000
                  ? `${(docComplete.document_length_chars / 1000).toFixed(1)}K chars`
                  : `${docComplete.document_length_chars} chars`}
              </span>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-400">Synthesizing documentation...</div>
        )}
      </div>
    )
  }

  return (
    <div className="text-sm text-gray-500">
      No details available for this documentation step.
    </div>
  )
}
