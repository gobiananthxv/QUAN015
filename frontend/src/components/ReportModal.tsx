import { useEffect, useRef, useState } from 'react'
import { ApiError, api, type SendReportResult } from '../api'

const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]+([.-][a-zA-Z0-9]+)*\.[a-zA-Z]{2,}$/

/**
 * Turn a refusal into something the person reading it can act on.
 *
 * The API's own messages name environment variables, which is right for
 * whoever runs the platform and wrong for whoever is standing at the dashboard.
 * The distinction the codes carry is what makes this possible: 401 is always a
 * credential problem and 403 is always the recipient policy, so neither case
 * has to guess which advice to give.
 *
 * Anything unrecognised falls through to the server's text rather than a
 * generic apology — an unexpected failure is more useful stated than softened.
 */
function reportErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return err instanceof Error ? err.message : 'Failed to send report email.'
  }
  switch (err.status) {
    case 401:
      return 'This dashboard is not authorised to send reports. Check that its access token matches the server.'
    case 403:
      return 'That address is not approved to receive reports. Ask whoever runs this platform to add it.'
    case 429:
      return 'Too many reports requested recently. Please try again in a few minutes.'
    case 503:
      return 'Email delivery is not configured on the server yet.'
    default:
      return err.message
  }
}

interface ReportModalProps {
  open: boolean
  onClose: () => void
}

export function ReportModal({ open, onClose }: ReportModalProps) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SendReportResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setEmail('')
      setError(null)
      setResult(null)
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open && !loading) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, loading, onClose])

  if (!open) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = email.trim()

    if (!trimmed) {
      setError('Email address is required.')
      return
    }

    if (!EMAIL_REGEX.test(trimmed)) {
      setError('Please enter a valid email address (e.g. user@example.com).')
      return
    }

    setError(null)
    setLoading(true)

    try {
      const res = await api.sendReport(trimmed)
      setResult(res)
    } catch (err: unknown) {
      setError(reportErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={loading ? undefined : onClose}>
      <div
        className="modal-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-modal-title"
      >
        <div className="modal-header">
          <div className="modal-header-text">
            <h2 id="report-modal-title">📊 Generate &amp; Email Report</h2>
            <p>Send all generated outputs, regime models, and plots to your email</p>
          </div>
          <button
            className="modal-close-btn"
            onClick={onClose}
            disabled={loading}
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          {result ? (
            <div className="modal-success">
              <div className="success-icon">✓</div>
              <h3>Report Sent Successfully!</h3>
              <p>
                All files and folders from <code>backend/output</code> have been emailed to{' '}
                <strong>{result.recipient ?? email}</strong>.
              </p>
              {result.files && result.files.length > 0 && (
                <div className="modal-files-list">
                  <span className="modal-files-label">
                    Included Files &amp; Folders ({result.files_count ?? result.files.length}):
                  </span>
                  <ul>
                    {result.files.map((file) => (
                      <li key={file}>
                        <code>{file}</code>
                      </li>
                    ))}
                  </ul>
                  <small className="modal-zip-note">
                    📦 All files and directory structures are also bundled in <code>output_report.zip</code>.
                  </small>
                </div>
              )}
              <div className="modal-actions" style={{ marginTop: '20px' }}>
                <button className="btn primary" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              <p className="modal-description">
                Enter your recipient email address below. The system will package all files and
                directories in <code>backend/output/</code> (including equity curves, regimes, strategy
                parameters, and visualization plots) and deliver them via SMTP.
              </p>

              <div className="form-group">
                <label htmlFor="report-email-input">Recipient Email Address</label>
                <input
                  ref={inputRef}
                  id="report-email-input"
                  type="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    if (error) setError(null)
                  }}
                  placeholder="analyst@firm.com"
                  disabled={loading}
                  className={error ? 'input-error' : ''}
                  autoComplete="email"
                />
                {error && <div className="form-error">{error}</div>}
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={onClose}
                  disabled={loading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn primary"
                  disabled={loading || !email.trim()}
                >
                  {loading ? (
                    <span className="btn-loading">
                      <span className="btn-spinner" />
                      Sending Report…
                    </span>
                  ) : (
                    'Send Report'
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
