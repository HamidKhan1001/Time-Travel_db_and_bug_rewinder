import { useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import { EmptyState } from '../components/ui/StateBlocks.jsx'
import { usePageTitle } from '../hooks/usePageTitle.js'

export default function NotFoundPage() {
  usePageTitle('Page not found')
  const navigate = useNavigate()
  return (
    <div className="max-w-xl mx-auto p-4 md:p-6">
      <Card hover={false} className="mt-6">
        <EmptyState
          icon="explore_off"
          title="Page not found"
          body="This page doesn't exist. Use the Console or the Audit log."
          action={
            <Button variant="primary" icon="arrow_back" onClick={() => navigate('/console')}>
              Go to Console
            </Button>
          }
        />
      </Card>
    </div>
  )
}
