/**
 * Detail views for content type classification and generation observability steps.
 */

import { useObservabilityStore } from '../../../stores/observabilityStore'

export function ContentTypeDetails({ node }: { node: string }) {
  const {
    contentTypeClassification,
    socialPostProgress,
    blogPostProgress,
    articleProgress,
    tutorialProgress,
    contentComplete,
  } = useObservabilityStore()

  // Content Type Classifier node
  if (node === 'content_type_classifier') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {contentTypeClassification ? (
          <>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Content Type:</span>
              <span className="px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-300 font-medium">
                {contentTypeClassification.content_type.replace('_', ' ')}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-200">Confidence:</span>
              <span className="text-green-400">{(contentTypeClassification.confidence * 100).toFixed(0)}%</span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-gray-400">Target Length:</span>
                <span className="ml-1 text-gray-200">{contentTypeClassification.target_length} words</span>
              </div>
              <div>
                <span className="text-gray-400">Tone:</span>
                <span className="ml-1 text-gray-200">{contentTypeClassification.tone}</span>
              </div>
              <div>
                <span className="text-gray-400">Retrieval Passes:</span>
                <span className="ml-1 text-gray-200">{contentTypeClassification.retrieval_depth}</span>
              </div>
              <div>
                <span className="text-gray-400">Temperature:</span>
                <span className="ml-1 text-gray-200">{contentTypeClassification.temperature}</span>
              </div>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-400">Classifying content type...</div>
        )}
      </div>
    )
  }

  // Social Post Generator node
  if (node === 'social_content_generator') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {socialPostProgress && socialPostProgress.length > 0 && (
          <div className="space-y-2">
            {socialPostProgress.map((event, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs text-gray-400 capitalize">{event.stage}:</span>
                <span className="text-xs text-gray-300">{event.message}</span>
              </div>
            ))}
          </div>
        )}

        {contentComplete && (
          <div className="grid grid-cols-2 gap-2 text-xs mt-2 pt-2 border-t border-gray-700">
            <div>
              <span className="text-gray-400">Words:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_words}</span>
            </div>
            <div>
              <span className="text-gray-400">Characters:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_chars}</span>
            </div>
          </div>
        )}

        {!socialPostProgress && !contentComplete && (
          <div className="text-sm text-gray-400">Generating social post...</div>
        )}
      </div>
    )
  }

  // Blog Post Generator node
  if (node === 'blog_content_generator') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {blogPostProgress && blogPostProgress.length > 0 && (
          <div className="space-y-2">
            {blogPostProgress.map((event, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs text-gray-400 capitalize">{event.stage.replace(/_/g, ' ')}:</span>
                <span className="text-xs text-gray-300">{event.message}</span>
              </div>
            ))}
          </div>
        )}

        {contentComplete && (
          <div className="grid grid-cols-2 gap-2 text-xs mt-2 pt-2 border-t border-gray-700">
            <div>
              <span className="text-gray-400">Words:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_words}</span>
            </div>
            <div>
              <span className="text-gray-400">Characters:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_chars}</span>
            </div>
          </div>
        )}

        {!blogPostProgress && !contentComplete && (
          <div className="text-sm text-gray-400">Generating blog post...</div>
        )}
      </div>
    )
  }

  // Technical Article Generator node
  if (node === 'article_content_generator') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {articleProgress && articleProgress.length > 0 && (
          <div className="space-y-2">
            {articleProgress.map((event, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs text-gray-400 capitalize">{event.stage.replace(/_/g, ' ')}:</span>
                <span className="text-xs text-gray-300">{event.message}</span>
              </div>
            ))}
          </div>
        )}

        {contentComplete && (
          <div className="grid grid-cols-2 gap-2 text-xs mt-2 pt-2 border-t border-gray-700">
            <div>
              <span className="text-gray-400">Words:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_words}</span>
            </div>
            <div>
              <span className="text-gray-400">Characters:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_chars}</span>
            </div>
          </div>
        )}

        {!articleProgress && !contentComplete && (
          <div className="text-sm text-gray-400">Generating technical article...</div>
        )}
      </div>
    )
  }

  // Tutorial Generator node
  if (node === 'tutorial_generator') {
    return (
      <div className="space-y-3 text-sm text-gray-100">
        {tutorialProgress && tutorialProgress.length > 0 && (
          <div className="space-y-2">
            {tutorialProgress.map((event, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs text-gray-400 capitalize">{event.stage.replace(/_/g, ' ')}:</span>
                <span className="text-xs text-gray-300">{event.message}</span>
              </div>
            ))}
          </div>
        )}

        {contentComplete && (
          <div className="grid grid-cols-2 gap-2 text-xs mt-2 pt-2 border-t border-gray-700">
            <div>
              <span className="text-gray-400">Words:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_words}</span>
            </div>
            <div>
              <span className="text-gray-400">Characters:</span>
              <span className="ml-1 text-green-400">{contentComplete.content_length_chars}</span>
            </div>
          </div>
        )}

        {!tutorialProgress && !contentComplete && (
          <div className="text-sm text-gray-400">Generating tutorial...</div>
        )}
      </div>
    )
  }

  return <div className="text-sm text-gray-400">No details available for this step.</div>
}
