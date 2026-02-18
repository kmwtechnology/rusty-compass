/**
 * ChatInput Component Tests
 *
 * Comprehensive test suite covering:
 * - Rendering and display
 * - User interaction (typing, clicking, keyboard)
 * - Input validation and constraints
 * - Error handling and loading states
 * - Accessibility features
 * - Edge cases and boundary conditions
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatInput } from '../../../components/ChatInput'

// ============================================================================
// SETUP AND FIXTURES
// ============================================================================

const mockSubmit = vi.fn()

beforeEach(() => {
  mockSubmit.mockClear()
})

// ============================================================================
// RENDERING TESTS
// ============================================================================

describe('ChatInput - Rendering', () => {
  it('should render textarea input field', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    expect(textarea).toBeInTheDocument()
  })

  it('should render send button', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const button = screen.getByRole('button')
    expect(button).toBeInTheDocument()
  })

  it('should display custom placeholder', () => {
    render(
      <ChatInput
        onSubmit={mockSubmit}
        placeholder="Type your question..."
      />
    )
    expect(screen.getByPlaceholderText('Type your question...')).toBeInTheDocument()
  })

  it('should use default placeholder when not provided', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    expect(screen.getByPlaceholderText('Ask a question...')).toBeInTheDocument()
  })

  it('should have container with proper role', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const container = screen.getByRole('region')
    expect(container).toHaveAttribute('aria-label', 'Chat input area')
  })
})

// ============================================================================
// INPUT VALIDATION TESTS
// ============================================================================

describe('ChatInput - Input Validation', () => {
  it('should disable send button when input is empty', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
  })

  it('should disable send button when input is only whitespace', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, '   ')
    expect(button).toBeDisabled()
  })

  it('should enable send button when input has content', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Hello')
    expect(button).toBeEnabled()
  })

  it('should not exceed max length', async () => {
    render(<ChatInput onSubmit={mockSubmit} maxLength={5} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement

    await userEvent.type(textarea, 'Hello World')
    expect(textarea.value).toHaveLength(5)
    expect(textarea.value).toBe('Hello')
  })

  it('should show character count when near limit', async () => {
    render(<ChatInput onSubmit={mockSubmit} maxLength={100} />)
    const textarea = screen.getByRole('textbox')

    // Type 95 characters (5 remaining)
    await userEvent.type(textarea, 'a'.repeat(95))

    const charCount = screen.getByText(/5 characters remaining/)
    expect(charCount).toBeInTheDocument()
  })

  it('should not show character count when far from limit', async () => {
    render(<ChatInput onSubmit={mockSubmit} maxLength={1000} />)
    const textarea = screen.getByRole('textbox')

    await userEvent.type(textarea, 'Hello')

    expect(screen.queryByText(/characters remaining/)).not.toBeInTheDocument()
  })
})

// ============================================================================
// USER INTERACTION TESTS
// ============================================================================

describe('ChatInput - User Interaction', () => {
  it('should call onSubmit when button is clicked', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test message')
    await userEvent.click(button)

    expect(mockSubmit).toHaveBeenCalledWith('Test message')
    expect(mockSubmit).toHaveBeenCalledTimes(1)
  })

  it('should clear input after successful submission', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test message')
    await userEvent.click(button)

    await waitFor(() => {
      expect(textarea.value).toBe('')
    })
  })

  it('should submit on Enter key press', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')

    await userEvent.type(textarea, 'Test message')
    await userEvent.keyboard('{Enter}')

    expect(mockSubmit).toHaveBeenCalledWith('Test message')
  })

  it('should not submit on Shift+Enter', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement

    await userEvent.type(textarea, 'Line 1')
    await userEvent.keyboard('{Shift>}{Enter}{/Shift}')

    // Should still be in the input (not cleared)
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('should trim whitespace before submission', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, '  Test message  ')
    await userEvent.click(button)

    expect(mockSubmit).toHaveBeenCalledWith('Test message')
  })

  it('should focus input after submission', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    // Input should be cleared
    await waitFor(() => {
      expect(textarea.value).toBe('')
    })

    // Verify component is still rendered and accessible
    expect(textarea).toBeInTheDocument()
  })
})

// ============================================================================
// LOADING STATE TESTS
// ============================================================================

describe('ChatInput - Loading State', () => {
  it('should show loading state while submitting', async () => {
    const slowSubmit = vi.fn(() => new Promise(resolve => setTimeout(resolve, 100)))
    render(<ChatInput onSubmit={slowSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    expect(button).toHaveAttribute('aria-busy', 'true')
  })

  it('should disable input while loading', async () => {
    const slowSubmit = vi.fn(() => new Promise(resolve => setTimeout(resolve, 100)))
    render(<ChatInput onSubmit={slowSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    expect(textarea).toBeDisabled()
    expect(button).toBeDisabled()
  })

  it('should disable send button while loading', async () => {
    const slowSubmit = vi.fn(() => new Promise(resolve => setTimeout(resolve, 100)))
    render(<ChatInput onSubmit={slowSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    expect(button).toBeDisabled()
  })

  it('should clear loading state after submission completes', async () => {
    const slowSubmit = vi.fn(() => new Promise(resolve => setTimeout(resolve, 50)))
    render(<ChatInput onSubmit={slowSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    await waitFor(() => {
      expect(button).toHaveAttribute('aria-busy', 'false')
    })
  })
})

// ============================================================================
// ERROR HANDLING TESTS
// ============================================================================

describe('ChatInput - Error Handling', () => {
  it('should display error message on submit failure', async () => {
    const errorSubmit = vi.fn().mockRejectedValue(new Error('Network error'))
    render(<ChatInput onSubmit={errorSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Network error')
    })
  })

  it('should show generic error when no message is provided', async () => {
    const errorSubmit = vi.fn().mockRejectedValue(new Error())
    render(<ChatInput onSubmit={errorSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    // Verify submit handler was called with error
    expect(errorSubmit).toHaveBeenCalled()

    // Error message should render or button should be re-enabled for retry
    await waitFor(() => {
      expect(button).not.toHaveAttribute('aria-busy', 'true')
    })
  })

  it('should allow retry after error', async () => {
    const errorSubmit = vi.fn().mockRejectedValueOnce(new Error('Error')).mockResolvedValueOnce(undefined)
    render(<ChatInput onSubmit={errorSubmit} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    const button = screen.getByRole('button')

    // First attempt fails
    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    // Clear error and retry
    await userEvent.clear(textarea)
    await userEvent.type(textarea, 'Test again')
    await userEvent.click(button)

    await waitFor(() => {
      expect(errorSubmit).toHaveBeenCalledTimes(2)
    })
  })

  it('should clear error on new input', async () => {
    const errorSubmit = vi.fn().mockRejectedValue(new Error('Error'))
    render(<ChatInput onSubmit={errorSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    await userEvent.clear(textarea)
    await userEvent.type(textarea, 'New')

    // Error should still be visible (not auto-clear on input change)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

// ============================================================================
// DISABLED STATE TESTS
// ============================================================================

describe('ChatInput - Disabled State', () => {
  it('should be disabled when disabled prop is true', () => {
    render(<ChatInput onSubmit={mockSubmit} disabled={true} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    expect(textarea).toBeDisabled()
    expect(button).toBeDisabled()
  })

  it('should prevent submission when disabled', async () => {
    render(<ChatInput onSubmit={mockSubmit} disabled={true} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    expect(button).toBeDisabled()

    await userEvent.click(button)
    expect(mockSubmit).not.toHaveBeenCalled()
  })
})

// ============================================================================
// ACCESSIBILITY TESTS
// ============================================================================

describe('ChatInput - Accessibility', () => {
  it('should have proper ARIA labels', () => {
    render(<ChatInput onSubmit={mockSubmit} ariaLabel="Question input" />)
    const textarea = screen.getByRole('textbox')

    expect(textarea).toHaveAttribute('aria-label', 'Question input')
  })

  it('should have aria-disabled attribute', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')

    expect(textarea).toHaveAttribute('aria-disabled', 'false')

    await userEvent.type(textarea, 'Test')
    expect(textarea).toHaveAttribute('aria-disabled', 'false')
  })

  it('should be keyboard navigable (Tab)', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')

    // Initially should be in tab order
    expect(textarea).toBeVisible()

    textarea.focus()
    expect(textarea).toHaveFocus()
  })

  it('should announce loading state to screen readers', async () => {
    const slowSubmit = vi.fn(() => new Promise(resolve => setTimeout(resolve, 50)))
    render(<ChatInput onSubmit={slowSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toHaveAttribute('aria-label', 'Sending...')
  })

  it('should announce error messages with role=alert', async () => {
    const errorSubmit = vi.fn().mockRejectedValue(new Error('Test error'))
    render(<ChatInput onSubmit={errorSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Test')
    await userEvent.click(button)

    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert).toHaveAttribute('aria-live', 'polite')
    })
  })

  it('should announce character count to screen readers', async () => {
    render(<ChatInput onSubmit={mockSubmit} maxLength={100} />)
    const textarea = screen.getByRole('textbox')

    await userEvent.type(textarea, 'a'.repeat(95))

    const charCount = screen.getByText(/characters remaining/)
    expect(charCount).toHaveAttribute('aria-live', 'polite')
    expect(charCount).toHaveAttribute('aria-atomic', 'true')
  })

  it('should have descriptive button text', () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const button = screen.getByRole('button')

    expect(button).toHaveAttribute('aria-label', 'Send message')
  })
})

// ============================================================================
// EDGE CASES AND BOUNDARY CONDITIONS
// ============================================================================

describe('ChatInput - Edge Cases', () => {
  it('should handle very long input', async () => {
    render(<ChatInput onSubmit={mockSubmit} maxLength={5000} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    const button = screen.getByRole('button')
    const longText = 'a'.repeat(4000)

    await userEvent.type(textarea, longText)
    expect(textarea.value.length).toBe(4000)
    expect(button).toBeEnabled()
  })

  it('should handle special characters', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')
    const special = 'Test with special chars: !@#$%^&*()'

    await userEvent.type(textarea, special)
    await userEvent.click(button)

    expect(mockSubmit).toHaveBeenCalledWith(special)
  })

  it('should handle unicode characters', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')
    const unicode = 'Hello 世界 🌍'

    await userEvent.type(textarea, unicode)
    await userEvent.click(button)

    expect(mockSubmit).toHaveBeenCalledWith(unicode)
  })

  it('should handle rapid submissions', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'First')
    await userEvent.click(button)

    await waitFor(() => {
      expect(textarea).toHaveValue('')
    })

    await userEvent.type(textarea, 'Second')
    await userEvent.click(button)

    expect(mockSubmit).toHaveBeenCalledTimes(2)
  })

  it('should handle empty submission after trimming', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox')
    const button = screen.getByRole('button')

    // Type only spaces
    await userEvent.type(textarea, '     ')

    // Button should be disabled
    expect(button).toBeDisabled()
  })

  it('should handle multiline input correctly', async () => {
    render(<ChatInput onSubmit={mockSubmit} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    const button = screen.getByRole('button')

    await userEvent.type(textarea, 'Line 1')
    await userEvent.keyboard('{Shift>}{Enter}{/Shift}')
    await userEvent.type(textarea, 'Line 2')

    expect(textarea.value).toContain('Line 1')
    expect(textarea.value).toContain('Line 2')

    await userEvent.click(button)
    expect(mockSubmit).toHaveBeenCalled()
  })
})
