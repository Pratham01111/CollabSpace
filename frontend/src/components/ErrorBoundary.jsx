import { Component } from 'react'

/**
 * Last line of defence for render errors. Without it, one exception anywhere
 * in the tree unmounts the whole app and leaves a blank page.
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Unhandled render error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="page">
        <div className="error-state" role="alert">
          <p className="error-state-title">Something went wrong on this page.</p>
          <p className="error-state-message">
            Reloading usually fixes it. Your work is saved on the server, not in this page.
          </p>
          <div className="error-state-actions">
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload
            </button>
            <a className="btn" href="/workspaces">Go to my workspaces</a>
          </div>
        </div>
      </div>
    )
  }
}
