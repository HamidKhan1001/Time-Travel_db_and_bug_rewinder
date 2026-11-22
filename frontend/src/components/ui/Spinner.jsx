export default function Spinner({ className = 'w-4 h-4' }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full border-2 border-current border-r-transparent animate-spin ${className}`}
      role="status"
      aria-label="Loading"
    />
  )
}
