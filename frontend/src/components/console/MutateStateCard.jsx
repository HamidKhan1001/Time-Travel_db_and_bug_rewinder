import { useDemo } from '../../context/DemoContext.jsx'
import Button from '../ui/Button.jsx'
import Card from '../ui/Card.jsx'

const LINE_DOT = { danger: 'bg-rose-500', success: 'bg-emerald-500', info: 'bg-blue-500' }

/** "Mutate State" card: the demo actions that cause and re-check the incident (PRD §5 steps 1, 2, 6). */
export default function MutateStateCard() {
  const { snapshot, pending, recovery, triggerWarehouseSync, placeOrders } = useDemo()
  const data = snapshot.data
  const busy = recovery.status === 'running' || pending.approve || pending.undo
  const ordersPlaced = Boolean(data?.orders?.length)

  return (
    <Card className="p-4 flex flex-col justify-between gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Mutate State</span>
        <span className="text-[11px] text-slate-400 font-mono bg-slate-100 px-2 py-0.5 rounded border border-slate-200/60">
          DB {data?.dbVersion || '—'}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <Button
          variant="danger-soft"
          size="md"
          icon="sync"
          className="!py-2.5 text-[12px]"
          onClick={triggerWarehouseSync}
          loading={pending.sync}
          loadingText="Syncing…"
          disabled={!data || busy}
          title={data?.patched ? 'Run the same sync again to check the fix' : 'Simulates the bad sync that causes the incident'}
        >
          {data?.patched ? 'Re-run Sync' : 'Sync Warehouse'}
        </Button>
        <Button
          variant="primary"
          size="md"
          icon="add_shopping_cart"
          className="!py-2.5 text-[12px]"
          onClick={placeOrders}
          loading={pending.orders}
          loadingText="Placing…"
          disabled={!data || busy || ordersPlaced}
          title={ordersPlaced ? 'Orders #1041–#1043 are already placed. Reset the demo to place them again.' : 'Adds orders #1041–#1043'}
        >
          Place 3 Orders
        </Button>
      </div>
      <div className="flex items-center justify-between gap-2 text-[11px] bg-slate-50/90 px-3 py-2 rounded-lg border border-slate-200/70 font-mono min-h-[34px]">
        {data?.lastAction ? (
          <>
            <div className="flex items-center gap-2 min-w-0">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${LINE_DOT[data.lastAction.tone] || 'bg-slate-400'}`} />
              <span className="text-slate-700 font-medium font-sans text-[12px] truncate">{data.lastAction.label}</span>
            </div>
            <span className="text-slate-400 font-medium shrink-0">{data.lastAction.time}</span>
          </>
        ) : (
          <span className="text-slate-400 font-sans text-[12px]">No actions yet. Run the warehouse sync to start the demo.</span>
        )}
      </div>
    </Card>
  )
}
