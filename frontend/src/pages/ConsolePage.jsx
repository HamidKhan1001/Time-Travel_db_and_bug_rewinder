import { useDemo } from '../context/DemoContext.jsx'
import ScenarioCard from '../components/console/ScenarioCard.jsx'
import MutateStateCard from '../components/console/MutateStateCard.jsx'
import InventoryCard from '../components/console/InventoryCard.jsx'
import OrdersStream from '../components/console/OrdersStream.jsx'
import ChangeLogFeed from '../components/console/ChangeLogFeed.jsx'
import RecoveryComposer from '../components/console/RecoveryComposer.jsx'
import RecoveryStatusPanel from '../components/console/RecoveryStatusPanel.jsx'
import { usePageTitle } from '../hooks/usePageTitle.js'

/** Console — Incident screen (Stitch export: console-incident). */
export default function ConsolePage() {
  const { snapshot, loadSnapshot } = useDemo()
  usePageTitle('Console')
  const data = snapshot.data
  const unavailable = snapshot.status === 'error' && !data

  return (
    <div className="flex flex-col w-full max-w-[1600px] mx-auto p-4 md:p-6 gap-5">
      <h1 className="sr-only">Console</h1>
      <div className="grid grid-cols-1 lg:grid-cols-12 w-full gap-5">
        {/* LEFT: live database (8 cols) */}
        <section className="lg:col-span-8 flex flex-col gap-5 min-w-0" aria-label="Live database">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ScenarioCard />
            <MutateStateCard />
          </div>
          <InventoryCard snapshot={snapshot} onRetry={loadSnapshot} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <OrdersStream orders={data?.orders} unavailable={unavailable} />
            <ChangeLogFeed entries={data?.changeLog} unavailable={unavailable} />
          </div>
        </section>

        {/* RIGHT: time-travel recovery (4 cols) */}
        <section className="lg:col-span-4 flex flex-col gap-5 min-w-0 lg:sticky lg:top-20 lg:self-start" aria-label="Time-travel recovery">
          <RecoveryComposer />
          <RecoveryStatusPanel />
        </section>
      </div>
    </div>
  )
}
