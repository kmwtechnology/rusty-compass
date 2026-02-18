/**
 * Layout - Main application layout with three-panel design.
 *
 * Desktop:
 * ┌─────────────────────────────────────────────────────────────────┐
 * │  Conversations  │         Chat          │    Observability      │
 * │    Sidebar      │        Panel          │       Panel           │
 * │   (250px)       │       (50%)           │       (50%)           │
 * └─────────────────┴───────────────────────┴───────────────────────┘
 *
 * Mobile: Sidebar in drawer, Chat full width, Observability hidden
 */

import { useEffect, useState } from 'react'
import { Menu, X } from 'lucide-react'
import { ConversationsSidebar } from './ConversationsSidebar'
import { ChatPanel } from './ChatPanel'
import { ObservabilityPanel } from './ObservabilityPanel'

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(250)
  const [observabilityWidth, setObservabilityWidth] = useState(450)
  const [isResizingSidebar, setIsResizingSidebar] = useState(false)
  const [isResizingObservability, setIsResizingObservability] = useState(false)

  const closeSidebar = () => setSidebarOpen(false)

  const handleSidebarMouseDown = (event: React.MouseEvent) => {
    event.preventDefault()
    setIsResizingSidebar(true)
  }

  const handleObservabilityMouseDown = (event: React.MouseEvent) => {
    event.preventDefault()
    setIsResizingObservability(true)
  }

  useEffect(() => {
    if (!isResizingSidebar && !isResizingObservability) {
      document.body.style.cursor = ''
      return
    }

    document.body.style.cursor = 'col-resize'

    const handleMouseMove = (event: MouseEvent) => {
      if (isResizingSidebar) {
        const minWidth = 200
        const maxWidth = 400
        const newWidth = Math.min(Math.max(event.clientX, minWidth), maxWidth)
        setSidebarWidth(newWidth)
      }

      if (isResizingObservability) {
        const minWidth = 300
        const maxWidth = 700
        const minChatWidth = 400
        const viewportWidth = window.innerWidth
        // Calculate max width based on available space
        const usedByResizer = 4 // resizer handle width
        const availableSpace = viewportWidth - sidebarWidth - usedByResizer - minChatWidth
        const constrainedMaxWidth = Math.min(maxWidth, Math.max(minWidth, availableSpace))
        const rawWidth = viewportWidth - event.clientX
        const newWidth = Math.min(Math.max(rawWidth, minWidth), constrainedMaxWidth)
        setObservabilityWidth(newWidth)
      }
    }

    const handleMouseUp = () => {
      setIsResizingSidebar(false)
      setIsResizingObservability(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
    }
  }, [isResizingSidebar, isResizingObservability, sidebarWidth])

  return (
    <div className="flex h-screen bg-gray-900 text-gray-100">
      {/* Mobile menu button */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label={sidebarOpen ? 'Close conversations menu' : 'Open conversations menu'}
        aria-expanded={sidebarOpen}
        className="md:hidden fixed top-4 left-4 z-40 p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {sidebarOpen ? (
          <X className="w-6 h-6" />
        ) : (
          <Menu className="w-6 h-6" />
        )}
      </button>

      {/* Mobile overlay backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar - desktop visible, mobile in drawer */}
      <div
        className={`${
          sidebarOpen
            ? 'fixed inset-y-0 left-0 z-40 h-full'
            : 'hidden md:block md:flex-shrink-0 h-full'
        }`}
        style={{ width: `${sidebarWidth}px`, maxWidth: 'calc(100vw - 1rem)' }}
      >
        <ConversationsSidebar onConversationSelect={closeSidebar} />
      </div>

      {/* Resizer handle */}
      <div
        className="hidden md:flex w-4 cursor-col-resize select-none"
        onMouseDown={handleSidebarMouseDown}
        aria-hidden="true"
      >
        <div className="mx-auto h-full w-px bg-gray-800 hover:bg-gray-600 transition-colors" />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex min-w-0 overflow-hidden">
        {/* Chat panel */}
        <div className="flex-1 min-w-[400px] border-r border-gray-800 overflow-hidden">
          <ChatPanel />
        </div>

        {/* Observability resizer & panel */}
        <div className="hidden lg:flex items-stretch flex-shrink-0">
          <div
            className="flex items-stretch w-4 cursor-col-resize select-none"
            onMouseDown={handleObservabilityMouseDown}
            aria-hidden="true"
          >
            <div className="mx-auto h-full w-px bg-gray-800 hover:bg-gray-600 transition-colors" />
          </div>
          <div
            className="flex min-w-0 h-full overflow-hidden"
            style={{
              width: `${observabilityWidth}px`,
              minWidth: '300px',
              maxWidth: '700px',
            }}
          >
            <ObservabilityPanel />
          </div>
        </div>
      </div>
    </div>
  )
}
