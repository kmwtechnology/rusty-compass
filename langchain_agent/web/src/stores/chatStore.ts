/**
 * Zustand store for chat state management.
 * Handles messages, streaming state, and conversation metadata.
 */

import { create } from 'zustand'
import { apiGet } from '../utils/api'

// Message and citation types for chat display
export interface Citation {
  label: string
  url: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  status?: 'queued'
  citations?: Citation[]
}

export interface QueuedMessage {
  id: string
  content: string
  timestamp: Date
}

// Conversation summary for sidebar
export interface ConversationSummary {
  thread_id: string
  title: string
  created_at: string
  updated_at?: string
}

interface ChatState {
  // Current conversation
  threadId: string | null
  messages: ChatMessage[]
  isProcessing: boolean
  streamingContent: string
  queuedMessages: QueuedMessage[]

  // WebSocket state
  isConnected: boolean
  isConnecting: boolean
  connectionError: string | null

  // Conversation list
  conversations: ConversationSummary[]
  conversationsLoading: boolean

  // Focus trigger - increments when input should be focused
  inputFocusTrigger: number

  // Actions
  setThreadId: (threadId: string) => void
  addMessage: (message: ChatMessage) => void
  updateLastMessage: (content: string) => void
  updateMessageStatus: (id: string, status?: 'queued') => void
  setLastMessageCitations: (citations: Citation[]) => void
  setIsProcessing: (isProcessing: boolean) => void
  setStreamingContent: (content: string) => void
  appendStreamingContent: (chunk: string) => void
  finalizeStreaming: () => void
  clearMessages: () => void
  setConversations: (conversations: ConversationSummary[]) => void
  setConversationsLoading: (loading: boolean) => void
  upsertConversation: (conversation: ConversationSummary) => void
  setMessages: (messages: ChatMessage[]) => void
  loadConversation: (threadId: string) => Promise<void>
  startNewConversation: () => void
  setConnectionState: (connected: boolean, connecting: boolean, error: string | null) => void
  triggerInputFocus: () => void
  enqueueMessage: (message: QueuedMessage) => void
  dequeueMessage: () => QueuedMessage | null
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  threadId: null,
  messages: [],
  isProcessing: false,
  streamingContent: '',
  queuedMessages: [],
  isConnected: false,
  isConnecting: false,
  connectionError: null,
  conversations: [],
  conversationsLoading: false,
  inputFocusTrigger: 0,

  // Actions
  setThreadId: (threadId) => set({ threadId }),

  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message]
  })),

  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const lastIndex = messages.length - 1
      messages[lastIndex] = {
        ...messages[lastIndex],
        content,
        isStreaming: false,
      }
    }
    return { messages }
  }),

  updateMessageStatus: (id, status) => set((state) => ({
    messages: state.messages.map((message) => (
      message.id === id
        ? {
          ...message,
          status,
        }
        : message
    )),
  })),

  setLastMessageCitations: (citations) => set((state) => {
    const messages = [...state.messages]
    const lastIndex = messages.length - 1
    if (lastIndex >= 0 && messages[lastIndex].role === 'assistant') {
      messages[lastIndex] = {
        ...messages[lastIndex],
        citations,
      }
    }
    return { messages }
  }),

  setIsProcessing: (isProcessing) => set({ isProcessing }),

  setStreamingContent: (content) => set({ streamingContent: content }),

  appendStreamingContent: (chunk) => set((state) => ({
    streamingContent: state.streamingContent + chunk
  })),

  finalizeStreaming: () => {
    const { streamingContent, messages } = get()
    if (streamingContent) {
      const lastMessage = messages[messages.length - 1]
      if (lastMessage && lastMessage.role === 'assistant' && lastMessage.isStreaming) {
        set((state) => {
          const updatedMessages = [...state.messages]
          const lastIndex = updatedMessages.length - 1
          updatedMessages[lastIndex] = {
            ...updatedMessages[lastIndex],
            content: streamingContent,
            isStreaming: false,
          }
          return {
            messages: updatedMessages,
            streamingContent: '',
            isProcessing: false,
          }
        })
      } else {
        set({
          streamingContent: '',
          isProcessing: false,
        })
      }
    } else {
      set({ isProcessing: false })
    }
  },

  clearMessages: () => set({ messages: [], streamingContent: '', queuedMessages: [] }),

  setConversations: (conversations) => set({ conversations }),

  setConversationsLoading: (loading) => set({ conversationsLoading: loading }),

  upsertConversation: (conversation) => set((state) => {
    const existingIndex = state.conversations.findIndex(
      (c) => c.thread_id === conversation.thread_id
    )
    if (existingIndex >= 0) {
      // Update existing conversation and move to top
      const updated = [...state.conversations]
      updated.splice(existingIndex, 1)
      return { conversations: [conversation, ...updated] }
    } else {
      // Add new conversation at the top
      return { conversations: [conversation, ...state.conversations] }
    }
  }),

  setMessages: (messages) => set({ messages }),

  loadConversation: async (threadId) => {
    try {
      // Always set the threadId first so connection can be attempted
      set({ threadId, connectionError: null })

      console.log('Loading conversation:', threadId)
      const response = await apiGet(`/api/conversations/${threadId}`)

      console.log('Conversation API response:', response.status, response.statusText)

      if (!response.ok) {
        const errorText = await response.text()
        console.error('Failed to load conversation:', response.status, response.statusText, errorText)
        // Still allow connection even if message history fails to load
        set({
          messages: [],
          streamingContent: '',
          isProcessing: false,
          queuedMessages: [],
        })
        return
      }

      const data = await response.json()
      console.log('Conversation data loaded:', data)

      const messages: ChatMessage[] = data.messages.map((msg: { type: string; content: string }, index: number) => ({
        id: `msg-${threadId}-${index}`,
        role: msg.type === 'human' ? 'user' : 'assistant',
        content: msg.content,
        timestamp: new Date(data.created_at),
      }))

      set({
        messages,
        streamingContent: '',
        isProcessing: false,
        connectionError: null,
        queuedMessages: [],
      })
    } catch (error) {
      console.error('Error loading conversation:', error)
      // Still set threadId so connection attempt can proceed
      set({
        threadId,
        messages: [],
        streamingContent: '',
        isProcessing: false,
        queuedMessages: [],
      })
    }
  },

  startNewConversation: () => {
    const newThreadId = `conversation_${Math.random().toString(36).slice(2, 10)}`
    set({
      threadId: newThreadId,
      messages: [],
      streamingContent: '',
      isProcessing: false,
      queuedMessages: [],
    })
  },

  setConnectionState: (connected, connecting, error) => set({
    isConnected: connected,
    isConnecting: connecting,
    connectionError: error,
  }),

  triggerInputFocus: () => set((state) => ({
    inputFocusTrigger: state.inputFocusTrigger + 1
  })),

  enqueueMessage: (message) => set((state) => ({
    queuedMessages: [...state.queuedMessages, message]
  })),

  dequeueMessage: () => {
    const { queuedMessages } = get()
    if (queuedMessages.length === 0) return null
    const [next, ...rest] = queuedMessages
    set({ queuedMessages: rest })
    return next
  },
}))
