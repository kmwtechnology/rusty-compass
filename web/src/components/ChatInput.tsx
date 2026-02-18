/**
 * ChatInput Component
 *
 * Provides user input interface for the chat application.
 * Handles text submission, validation, keyboard interaction, and loading states.
 */

import React, { useState, useRef, useEffect } from 'react'

export interface ChatInputProps {
  onSubmit: (message: string) => Promise<void> | void
  disabled?: boolean
  placeholder?: string
  maxLength?: number
  ariaLabel?: string
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSubmit,
  disabled = false,
  placeholder = 'Ask a question...',
  maxLength = 2000,
  ariaLabel = 'Chat input'
}) => {
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Trim whitespace for validation
  const trimmedInput = input.trim()
  const isValid = trimmedInput.length > 0 && trimmedInput.length <= maxLength

  const handleSubmit = async () => {
    if (!isValid || isLoading) return

    try {
      setIsLoading(true)
      setError(null)
      await onSubmit(trimmedInput)
      setInput('')
      inputRef.current?.focus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const remainingChars = maxLength - input.length

  return (
    <div className="chat-input-container" role="region" aria-label="Chat input area">
      {error && (
        <div className="error-message" role="alert" aria-live="polite">
          {error}
        </div>
      )}

      <div className="input-wrapper">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isLoading}
          placeholder={placeholder}
          maxLength={maxLength}
          aria-label={ariaLabel}
          aria-disabled={disabled || isLoading}
          rows={1}
          className="chat-textarea"
        />

        <button
          onClick={handleSubmit}
          disabled={!isValid || isLoading || disabled}
          aria-label={isLoading ? 'Sending...' : 'Send message'}
          aria-busy={isLoading}
          className="send-button"
        >
          {isLoading ? (
            <>
              <span aria-hidden="true">⏳</span>
              <span className="sr-only">Sending...</span>
            </>
          ) : (
            <>
              <span aria-hidden="true">→</span>
              <span className="sr-only">Send</span>
            </>
          )}
        </button>
      </div>

      {remainingChars < 100 && remainingChars >= 0 && (
        <div className="char-count" aria-live="polite" aria-atomic="true">
          {remainingChars} characters remaining
        </div>
      )}
    </div>
  )
}

export default ChatInput
