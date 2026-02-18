/**
 * StepCard - Expandable card showing details of a single execution step.
 */

import { ChevronDown, ChevronRight, Clock } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type {
  AgentEvent,
  IntentClassificationEvent,
  ObservabilityStep,
  SummaryEvent,
  AlphaRefinementEvent,
} from '../../types/events'
import { QueryEvaluatorDetails } from './details/QueryEvaluatorDetails'
import { SearchDetails } from './details/SearchDetails'
import { LLMAgentDetails } from './details/LLMAgentDetails'
import { IntentClassifierDetails } from './details/IntentClassifierDetails'
import { SummaryDetails } from './details/SummaryDetails'
import { ConfigBuilderDetails } from './details/ConfigBuilderDetails'
import { DocWriterDetails } from './details/DocWriterDetails'
import { ContentTypeDetails } from './details/ContentTypeDetails'
import clsx from 'clsx'

interface StepCardProps {
  step: ObservabilityStep
  index: number
}

// Node display configuration
const nodeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  query_evaluator: {
    label: 'Query Evaluator',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10 border-blue-500/30',
  },
  agent: {
    label: 'LLM Agent',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/10 border-cyan-500/30',
  },
  retriever: {
    label: 'Knowledge Search',
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/10 border-violet-500/30',
  },
  alpha_refiner: {
    label: 'Alpha Refiner',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10 border-orange-500/30',
  },
  intent_classifier: {
    label: 'Intent Classifier',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10 border-emerald-500/30',
  },
  // Config builder nodes (amber)
  config_resolver: {
    label: 'Config Resolver',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10 border-amber-500/30',
  },
  config_generator: {
    label: 'Config Generator',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10 border-amber-500/30',
  },
  config_response: {
    label: 'Config Response',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10 border-amber-500/30',
  },
  // Doc writer nodes (teal)
  doc_planner: {
    label: 'Doc Planner',
    color: 'text-teal-400',
    bgColor: 'bg-teal-500/10 border-teal-500/30',
  },
  doc_gatherer: {
    label: 'Doc Gatherer',
    color: 'text-teal-400',
    bgColor: 'bg-teal-500/10 border-teal-500/30',
  },
  doc_synthesizer: {
    label: 'Doc Synthesizer',
    color: 'text-teal-400',
    bgColor: 'bg-teal-500/10 border-teal-500/30',
  },
  // Content type nodes (purple)
  content_type_classifier: {
    label: 'Content Type Classifier',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
  social_content_generator: {
    label: 'Social Post Generator',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
  blog_content_generator: {
    label: 'Blog Post Generator',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
  article_content_generator: {
    label: 'Technical Article Generator',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
  tutorial_generator: {
    label: 'Tutorial Generator',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10 border-purple-500/30',
  },
}

export function StepCard({ step, index }: StepCardProps) {
  const { expandedSteps, toggleStepExpanded } = useObservabilityStore()
  const isExpanded = expandedSteps.has(step.id)

  const config = nodeConfig[step.node] || {
    label: step.node,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10 border-gray-500/30',
  }

  const statusColors = {
    idle: 'bg-gray-500',
    running: 'bg-blue-500 animate-pulse',
    complete: 'bg-emerald-500',
    error: 'bg-red-500',
  }

  return (
    <div
      className={clsx(
        'rounded-lg border transition-all',
        config.bgColor,
        step.status === 'running' && 'ring-2 ring-blue-500/50'
      )}
    >
      {/* Header - always visible */}
      <button
        onClick={() => toggleStepExpanded(step.id)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        {/* Expand icon */}
        <div className="flex-shrink-0 text-gray-500">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </div>

        {/* Step number */}
        <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-700 flex items-center justify-center text-xs text-gray-300">
          {index + 1}
        </div>

        {/* Status indicator */}
        <div className={clsx('w-2 h-2 rounded-full', statusColors[step.status])} />

        {/* Node name + summary */}
        <div className="flex-1 min-w-0 truncate">
          <span className={clsx('font-medium text-sm', config.color)}>
            {config.label}
          </span>
          {step.node !== 'intent_classifier' && step.summary && (
            <span className="ml-2 text-xs text-gray-500">
              {step.summary}
            </span>
          )}
        </div>

        {/* Duration */}
        {step.durationMs !== undefined && (
          <div className="flex-shrink-0 flex items-center gap-1 text-xs text-gray-500">
            <Clock className="w-3 h-3" />
            {step.durationMs < 1000
              ? `${Math.round(step.durationMs)}ms`
              : `${(step.durationMs / 1000).toFixed(1)}s`}
          </div>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-700/50 min-w-0 overflow-hidden">
          <StepDetails step={step} />
        </div>
      )}
    </div>
  )
}

function StepDetails({ step }: { step: ObservabilityStep }) {
  const { queryExpansion, alphaRefinement } = useObservabilityStore()

  switch (step.node) {
    case 'query_evaluator':
      return <QueryEvaluatorDetails />

    case 'retriever':
      return <SearchDetails />

    case 'agent':
      return <LLMAgentDetails step={step} />

    case 'intent_classifier': {
      const intentEvent = step.events.find(isIntentClassificationEvent)
      return <IntentClassifierDetails event={intentEvent} queryExpansion={queryExpansion} />
    }

    case 'alpha_refiner': {
      const refinementEvent = step.events.find(isAlphaRefinementEvent)
      return <AlphaRefinerDetails event={refinementEvent ?? alphaRefinement} />
    }

    case 'summary': {
      const summaryEvent = step.events.find(isSummaryEvent)
      return <SummaryDetails event={summaryEvent} status={step.status} />
    }

    // Config builder nodes
    case 'config_resolver':
    case 'config_generator':
    case 'config_response':
      return <ConfigBuilderDetails node={step.node} />

    // Doc writer nodes
    case 'doc_planner':
    case 'doc_gatherer':
    case 'doc_synthesizer':
      return <DocWriterDetails node={step.node} />

    // Content type nodes
    case 'content_type_classifier':
    case 'social_content_generator':
    case 'blog_content_generator':
    case 'article_content_generator':
    case 'tutorial_generator':
      return <ContentTypeDetails node={step.node} />

    default:
      return (
        <div className="text-sm text-gray-500">
          No details available for this step.
        </div>
      )
  }
}

function isIntentClassificationEvent(event: AgentEvent): event is IntentClassificationEvent {
  return event.type === 'intent_classification'
}

function isSummaryEvent(event: AgentEvent): event is SummaryEvent {
  return event.type === 'summary_generated'
}

function isAlphaRefinementEvent(event: AgentEvent): event is AlphaRefinementEvent {
  return event.type === 'alpha_refinement'
}

// Inline AlphaRefinerDetails component
function AlphaRefinerDetails({ event }: { event?: AlphaRefinementEvent | null }) {
  if (!event) {
    return (
      <div className="text-sm text-gray-400 animate-pulse">
        Evaluating alpha refinement…
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm text-gray-100">
      {/* Triggered status */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-200">Status:</span>
        <span className={clsx(
          'px-2 py-0.5 rounded text-xs font-medium',
          event.triggered
            ? 'bg-orange-500/20 text-orange-400'
            : 'bg-gray-500/20 text-gray-400'
        )}>
          {event.triggered ? 'Refinement Triggered' : 'No Refinement Needed'}
        </span>
      </div>

      {/* Max score with bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-gray-200">Max Reranker Score:</span>
          <span className={clsx(
            'text-xs',
            event.max_score < event.threshold ? 'text-orange-400' : 'text-green-400'
          )}>
            {(event.max_score * 100).toFixed(1)}%
          </span>
        </div>
        <div className="relative h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all',
              event.max_score < event.threshold ? 'bg-orange-500' : 'bg-green-500'
            )}
            style={{ width: `${event.max_score * 100}%` }}
          />
          {/* Threshold marker */}
          <div
            className="absolute top-0 h-full w-0.5 bg-yellow-400"
            style={{ left: `${event.threshold * 100}%` }}
            title={`Threshold: ${(event.threshold * 100).toFixed(0)}%`}
          />
        </div>
        <div className="flex justify-between text-xs text-gray-500">
          <span>Threshold: {(event.threshold * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Alpha adjustment */}
      {event.triggered && event.new_alpha != null && (
        <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/30">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400">Alpha adjusted:</span>
            <span className="text-gray-300">{event.original_alpha.toFixed(2)}</span>
            <span className="text-orange-400">→</span>
            <span className="text-orange-300 font-medium">{event.new_alpha.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Reason */}
      <div>
        <span className="font-semibold text-gray-200">Reason:</span>
        <p className="mt-1 text-gray-400">{event.reason}</p>
      </div>
    </div>
  )
}
