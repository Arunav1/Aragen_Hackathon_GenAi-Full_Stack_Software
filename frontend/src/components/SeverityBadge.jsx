const LABELS = {
  critical: { text: 'CRITICAL', icon: '🚨' },
  warning: { text: 'WARNING', icon: '⚠️' },
  normal: { text: 'NORMAL', icon: '✓' },
  unknown: { text: 'UNKNOWN', icon: '?' },
}

/** Red / Yellow / Green / Grey status chip. */
export default function SeverityBadge({ status, size = 'md' }) {
  const key = LABELS[status] ? status : 'unknown'
  const { text, icon } = LABELS[key]
  return (
    <span className={`badge badge-${key} badge-${size}`}>
      <span aria-hidden="true">{icon}</span>
      {text}
    </span>
  )
}
