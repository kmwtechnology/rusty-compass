/**
 * Chat Component Test Fixtures
 *
 * Provides reusable test data and mock functions for chat-related tests.
 */

import { vi } from 'vitest'

/**
 * Mock messages for testing
 */
export const mockMessages = {
  simple: 'Hello',
  question: 'How do I use Lucille?',
  long: 'This is a longer message with more content to test different input lengths.',
  specialChars: 'Test with special chars: !@#$%^&*()',
  unicode: 'Hello 世界 🌍 مرحبا',
  whitespaceOnly: '   ',
  multiline: 'Line 1\nLine 2\nLine 3',
  veryLong: 'a'.repeat(1000),
}

/**
 * Mock callbacks for testing
 */
export const createMockCallbacks = () => ({
  onSubmit: vi.fn(),
  onError: vi.fn(),
  onLoading: vi.fn(),
})

/**
 * Mock submit handlers with different behaviors
 */
export const createMockSubmitHandlers = () => ({
  /**
   * Instant success
   */
  instant: vi.fn().mockResolvedValue(undefined),

  /**
   * Slow but successful (100ms delay)
   */
  slow: vi.fn(
    () => new Promise(resolve => setTimeout(resolve, 100))
  ),

  /**
   * Fails with network error
   */
  networkError: vi.fn().mockRejectedValue(new Error('Network error')),

  /**
   * Fails with validation error
   */
  validationError: vi.fn().mockRejectedValue(new Error('Invalid input')),

  /**
   * Succeeds first call, fails second
   */
  failOnSecond: vi.fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new Error('Request failed')),

  /**
   * Alternate between success and failure
   */
  alternating: vi.fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new Error('Error'))
    .mockResolvedValueOnce(undefined),
})

/**
 * Create a mock submit function with custom delay
 */
export const createDelayedSubmit = (delayMs: number) =>
  vi.fn(() => new Promise(resolve => setTimeout(resolve, delayMs)))

/**
 * Create a mock submit function that throws after delay
 */
export const createDelayedError = (delayMs: number, message: string) =>
  vi.fn(() => new Promise((_, reject) => setTimeout(() => reject(new Error(message)), delayMs)))

/**
 * Component test configuration
 */
export const defaultChatInputProps = {
  placeholder: 'Ask a question...',
  maxLength: 2000,
  ariaLabel: 'Chat input',
}

/**
 * Custom ChatInput props for specific test scenarios
 */
export const chatInputScenarios = {
  /**
   * Short input field (good for mobile)
   */
  shortInput: {
    maxLength: 100,
    placeholder: 'Quick question...',
  },

  /**
   * Long input field (for detailed queries)
   */
  longInput: {
    maxLength: 5000,
    placeholder: 'Ask anything...',
  },

  /**
   * Accessibility-focused
   */
  accessible: {
    ariaLabel: 'Submit your question for Lucille documentation search',
    placeholder: 'Type your question about Lucille...',
  },

  /**
   * Minimal configuration
   */
  minimal: {
    placeholder: '',
    maxLength: 500,
  },
}

/**
 * Validation test cases
 */
export const validationCases = {
  valid: [
    'Hello',
    'How do I use Lucille?',
    'Tell me about connectors',
    'a'.repeat(100),
  ],
  invalid: [
    '',
    '   ',
    '\n\n\n',
    '\t\t\t',
  ],
  edge: [
    'a',
    'a'.repeat(2000),
    'a b',
    'special!@#chars',
  ],
}

/**
 * Keyboard event simulation helpers
 */
export const keyboardEvents = {
  /**
   * Simulate Enter key press
   */
  enter: { key: 'Enter', code: 'Enter' },

  /**
   * Simulate Shift+Enter (new line)
   */
  shiftEnter: { key: 'Enter', code: 'Enter', shiftKey: true },

  /**
   * Simulate Tab key
   */
  tab: { key: 'Tab', code: 'Tab' },

  /**
   * Simulate Escape key
   */
  escape: { key: 'Escape', code: 'Escape' },
}

/**
 * Error scenarios for testing error handling
 */
export const errorScenarios = {
  network: new Error('Network error'),
  timeout: new Error('Request timeout'),
  validation: new Error('Validation failed'),
  server: new Error('Server error'),
  unknown: new Error('Unknown error'),
}

/**
 * Accessibility test assertions
 */
export const accessibilityChecks = {
  /**
   * ARIA labels and descriptions
   */
  labels: {
    chatInput: 'Chat input area',
    textarea: 'Chat input',
    sendButton: 'Send message',
    loading: 'Sending...',
  },

  /**
   * ARIA roles
   */
  roles: {
    container: 'region',
    input: 'textbox',
    button: 'button',
    error: 'alert',
    status: 'status',
  },

  /**
   * ARIA attributes
   */
  attributes: {
    disabled: 'aria-disabled',
    busy: 'aria-busy',
    label: 'aria-label',
    live: 'aria-live',
    atomic: 'aria-atomic',
  },
}
