/**
 * Zustand store for observability state management.
 * Tracks agent execution steps and events.
 */

import { create } from 'zustand'
import type {
  AgentEvent,
  NodeName,
  NodeStatus,
  ObservabilityStep,
  QueryEvaluationEvent,
  DocumentGradingSummaryEvent,
  ResponseGradingEvent,
  SearchCandidate,
  RerankedDocument,
  ConversationContextEvent,
  IntentClassificationEvent,
  QueryExpansionEvent,
  AlphaRefinementEvent,
  ConfigBuilderStartEvent,
  ComponentSpecRetrievalEvent,
  ConfigGeneratedEvent,
  DocOutlineEvent,
  DocSectionProgressEvent,
  DocCompleteEvent,
  ContentTypeClassificationEvent,
  SocialPostProgressEvent,
  BlogPostProgressEvent,
  ArticleProgressEvent,
  TutorialProgressEvent,
  ContentCompleteEvent,
} from '../types/events'

interface ObservabilityState {
  // Current execution state
  isExecuting: boolean
  currentNode: NodeName | null
  steps: ObservabilityStep[]

  // Conversation context
  conversationContext: ConversationContextEvent | null

  // Key event data for display
  queryEvaluation: QueryEvaluationEvent | null
  intentClassification: IntentClassificationEvent | null
  queryExpansion: QueryExpansionEvent | null
  alphaRefinement: AlphaRefinementEvent | null
  searchCandidates: SearchCandidate[]
  rerankedDocuments: RerankedDocument[]
  documentGradingSummary: DocumentGradingSummaryEvent | null
  responseGrading: ResponseGradingEvent | null

  // Search status for interim messages ('idle' | 'running' | 'done')
  searchStatus: 'idle' | 'running' | 'done'
  rerankerStatus: 'idle' | 'running' | 'done'

  // Config builder state
  configBuilderStart: ConfigBuilderStartEvent | null
  componentSpecRetrieval: ComponentSpecRetrievalEvent | null
  configGenerated: ConfigGeneratedEvent | null

  // Doc writer state
  docOutline: DocOutlineEvent | null
  docSectionProgress: DocSectionProgressEvent | null
  docComplete: DocCompleteEvent | null

  // Content type state
  contentTypeClassification: ContentTypeClassificationEvent | null
  socialPostProgress: SocialPostProgressEvent[]
  blogPostProgress: BlogPostProgressEvent[]
  articleProgress: ArticleProgressEvent[]
  tutorialProgress: TutorialProgressEvent[]
  contentComplete: ContentCompleteEvent | null

  // Progress messages for real-time display
  searchProgressMessage: string | null
  rerankerProgressMessage: string | null
  rerankerProgress: number

  // UI state
  expandedSteps: Set<string>
  expandedEvents: Set<string>

  // Actions
  startExecution: () => void
  endExecution: () => void
  addEvent: (event: AgentEvent) => void
  startNode: (node: NodeName, summary?: string) => void
  endNode: (node: NodeName, durationMs: number, summary?: string) => void
  toggleStepExpanded: (stepId: string) => void
  toggleEventExpanded: (eventId: string) => void
  clearState: () => void
}

export const useObservabilityStore = create<ObservabilityState>((set, get) => ({
  // Initial state
  isExecuting: false,
  currentNode: null,
  steps: [],
  conversationContext: null,
  queryEvaluation: null,
  intentClassification: null,
  queryExpansion: null,
  alphaRefinement: null,
  searchCandidates: [],
  rerankedDocuments: [],
  documentGradingSummary: null,
  responseGrading: null,
  searchStatus: 'idle',
  rerankerStatus: 'idle',
  configBuilderStart: null,
  componentSpecRetrieval: null,
  configGenerated: null,
  docOutline: null,
  docSectionProgress: null,
  docComplete: null,
  contentTypeClassification: null,
  socialPostProgress: [],
  blogPostProgress: [],
  articleProgress: [],
  tutorialProgress: [],
  contentComplete: null,
  searchProgressMessage: null,
  rerankerProgressMessage: null,
  rerankerProgress: 0,
  expandedSteps: new Set(),
  expandedEvents: new Set(),

  // Actions
  startExecution: () => set({
    isExecuting: true,
    currentNode: null,
    steps: [],
    conversationContext: null,
    queryEvaluation: null,
    intentClassification: null,
    queryExpansion: null,
    alphaRefinement: null,
    searchCandidates: [],
    rerankedDocuments: [],
    documentGradingSummary: null,
    responseGrading: null,
    searchStatus: 'idle',
    rerankerStatus: 'idle',
    configBuilderStart: null,
    componentSpecRetrieval: null,
    configGenerated: null,
    docOutline: null,
    docSectionProgress: null,
    docComplete: null,
    contentTypeClassification: null,
    socialPostProgress: [],
    blogPostProgress: [],
    articleProgress: [],
    tutorialProgress: [],
    contentComplete: null,
    searchProgressMessage: null,
    rerankerProgressMessage: null,
    rerankerProgress: 0,
  }),

  endExecution: () => set({
    isExecuting: false,
    currentNode: null,
    searchProgressMessage: null,
    rerankerProgressMessage: null,
  }),

  addEvent: (event) => {
    const state = get()

    // Update specific event data based on type
    switch (event.type) {
      case 'conversation_context':
        set({ conversationContext: event as ConversationContextEvent })
        break

      case 'query_evaluation':
        set({ queryEvaluation: event as QueryEvaluationEvent })
        break

      case 'intent_classification':
        set({ intentClassification: event as IntentClassificationEvent })
        break

      case 'query_expansion':
        set({ queryExpansion: event as QueryExpansionEvent })
        break

      case 'alpha_refinement':
        set({ alphaRefinement: event as AlphaRefinementEvent })
        break

      case 'hybrid_search_start':
        set({ searchStatus: 'running', rerankerStatus: 'idle' })
        break

      case 'hybrid_search_result':
        set({
          searchStatus: 'done',
          searchCandidates: (event as { candidates: SearchCandidate[] }).candidates,
          rerankerStatus: 'idle',
        })
        break

      case 'reranker_start':
        set({ rerankerStatus: 'running' })
        break

      case 'reranker_result':
        set({
          rerankerStatus: 'done',
          rerankedDocuments: (event as { results: RerankedDocument[] }).results,
        })
        break

      case 'document_grading_summary':
        set({ documentGradingSummary: event as DocumentGradingSummaryEvent })
        break

      case 'response_grading':
        set({ responseGrading: event as ResponseGradingEvent })
        break

      case 'search_progress':
        set({ searchProgressMessage: (event as { message: string }).message })
        break

      case 'reranker_progress':
        set({
          rerankerProgressMessage: (event as { message: string }).message,
          rerankerProgress: (event as { progress: number }).progress,
        })
        break

      // Config builder events
      case 'config_builder_start':
        set({ configBuilderStart: event as ConfigBuilderStartEvent })
        break
      case 'component_spec_retrieval':
        set({ componentSpecRetrieval: event as ComponentSpecRetrievalEvent })
        break
      case 'config_generated':
        set({ configGenerated: event as ConfigGeneratedEvent })
        break

      // Doc writer events
      case 'doc_outline':
        set({ docOutline: event as DocOutlineEvent })
        break
      case 'doc_section_progress':
        set({ docSectionProgress: event as DocSectionProgressEvent })
        break
      case 'doc_complete':
        set({ docComplete: event as DocCompleteEvent })
        break

      // Content type events
      case 'content_type_classification':
        set({ contentTypeClassification: event as ContentTypeClassificationEvent })
        break
      case 'social_post_progress':
        set((s) => ({
          socialPostProgress: [...s.socialPostProgress, event as SocialPostProgressEvent],
        }))
        break
      case 'blog_post_progress':
        set((s) => ({
          blogPostProgress: [...s.blogPostProgress, event as BlogPostProgressEvent],
        }))
        break
      case 'article_progress':
        set((s) => ({
          articleProgress: [...s.articleProgress, event as ArticleProgressEvent],
        }))
        break
      case 'tutorial_progress':
        set((s) => ({
          tutorialProgress: [...s.tutorialProgress, event as TutorialProgressEvent],
        }))
        break
      case 'content_complete':
        set({ contentComplete: event as ContentCompleteEvent })
        break
    }

    // Add event to current step if there is one
    if (state.currentNode && state.steps.length > 0) {
      set((s) => {
        const steps = [...s.steps]
        const currentStepIndex = steps.findIndex(
          (step) => step.node === s.currentNode && step.status === 'running'
        )
        if (currentStepIndex >= 0) {
          steps[currentStepIndex] = {
            ...steps[currentStepIndex],
            events: [...steps[currentStepIndex].events, event],
          }
        }
        return { steps }
      })
    }
  },

  startNode: (node, summary) => {
    const stepId = `${node}-${Date.now()}`

    set((state) => ({
      currentNode: node,
      steps: [
        ...state.steps,
        {
          id: stepId,
          node,
          status: 'running' as NodeStatus,
          startTime: new Date(),
          events: [],
          summary,
        },
      ],
      expandedSteps: new Set([...state.expandedSteps, stepId]),
    }))
  },

  endNode: (node, durationMs, summary) => {
    set((state) => {
      const steps = [...state.steps]
      const stepIndex = steps.findIndex(
        (step) => step.node === node && step.status === 'running'
      )

      if (stepIndex >= 0) {
        steps[stepIndex] = {
          ...steps[stepIndex],
          status: 'complete',
          endTime: new Date(),
          durationMs,
          summary: summary || steps[stepIndex].summary,
        }
      }

      return {
        steps,
        currentNode: null,
      }
    })
  },

  toggleStepExpanded: (stepId) => set((state) => {
    const expandedSteps = new Set(state.expandedSteps)
    if (expandedSteps.has(stepId)) {
      expandedSteps.delete(stepId)
    } else {
      expandedSteps.add(stepId)
    }
    return { expandedSteps }
  }),

  toggleEventExpanded: (eventId) => set((state) => {
    const expandedEvents = new Set(state.expandedEvents)
    if (expandedEvents.has(eventId)) {
      expandedEvents.delete(eventId)
    } else {
      expandedEvents.add(eventId)
    }
    return { expandedEvents }
  }),

  clearState: () => set({
    isExecuting: false,
    currentNode: null,
    steps: [],
    conversationContext: null,
    queryEvaluation: null,
    intentClassification: null,
    queryExpansion: null,
    alphaRefinement: null,
    searchCandidates: [],
    rerankedDocuments: [],
    documentGradingSummary: null,
    responseGrading: null,
    searchStatus: 'idle',
    rerankerStatus: 'idle',
    configBuilderStart: null,
    componentSpecRetrieval: null,
    configGenerated: null,
    docOutline: null,
    docSectionProgress: null,
    docComplete: null,
    expandedSteps: new Set(),
    expandedEvents: new Set(),
  }),
}))
