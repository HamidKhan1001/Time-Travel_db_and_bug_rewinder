import { Component } from 'react'
import Button from './Button.jsx'
import Card from './Card.jsx'
import { EmptyState } from './StateBlocks.jsx'

/**
 * Catches errors thrown while rendering so one broken component shows a recoverable message
 * instead of a blank white page. Event-handler and async errors are handled where they happen (ApiError).
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI error caught by ErrorBoundary:', error, info?.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="max-w-xl mx-auto p-4 md:p-6" role="alert">
        <Card hover={false} className="mt-6">
          <EmptyState
            icon="error"
            title="Something went wrong"
            body="This screen hit an unexpected error. Your data is safe: nothing was changed. Try again, or reload the page."
            action={
              <div className="flex gap-2 justify-center">
                <Button variant="primary" icon="refresh" onClick={() => window.location.reload()}>
                  Reload
                </Button>
                <Button variant="secondary" onClick={this.reset}>
                  Try again
                </Button>
              </div>
            }
          />
        </Card>
      </div>
    )
  }
}
