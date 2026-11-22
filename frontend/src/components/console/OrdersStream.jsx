import Card, { CardIcon } from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import { SkeletonRows } from '../ui/Skeleton.jsx'

export function OrderStatusPill({ order }) {
  if (order.status === 'oversold') {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] bg-rose-50 border border-rose-200 text-rose-700 font-bold tracking-wide shrink-0">
        Oversold
      </span>
    )
  }
  if (order.status === 'partial') {
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] bg-amber-50 border border-amber-200 text-amber-800 font-bold tracking-wide shrink-0">
        {order.fulfilledQty}/{order.qty} · {order.backorderedQty} backordered
      </span>
    )
  }
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-50 border border-emerald-200 text-emerald-700 font-bold tracking-wide shrink-0">
      Fulfilled
    </span>
  )
}

/** "Orders Stream" card (Console Incident design). */
export default function OrdersStream({ orders, unavailable = false }) {
  return (
    <Card className="p-4 flex flex-col gap-3.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CardIcon icon="receipt_long" tone="blue" />
          <h2 className="font-bold text-slate-800 text-[13px]">Orders Stream</h2>
        </div>
        {orders && (
          <span className="px-2 py-0.5 rounded-full text-[10px] bg-blue-50 text-blue-700 border border-blue-200/80 font-bold">
            {orders.length} Active
          </span>
        )}
      </div>
      {unavailable ? (
        <p className="text-[12px] text-slate-400 py-6 text-center">Orders are unavailable until live data loads.</p>
      ) : !orders ? (
        <SkeletonRows rows={3} className="h-11" />
      ) : orders.length === 0 ? (
        <div className="flex flex-col items-center text-center gap-2 py-6">
          <Icon name="shopping_cart" className="text-[22px] text-slate-300" />
          <p className="text-[12px] text-slate-500">No orders since the last reset.</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {orders.map((order) => (
            <li
              key={order.id}
              className="bg-slate-50/80 hover:bg-slate-100/70 border border-slate-200/70 p-2.5 rounded-lg flex items-center justify-between gap-2 transition-colors"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span className="font-mono text-indigo-600 font-bold text-[13px] bg-indigo-50/70 px-2 py-0.5 rounded border border-indigo-100">
                  {order.id}
                </span>
                <span className="text-[12px] text-slate-600 font-medium truncate" title={order.item}>
                  {order.qty}x {order.sku}
                </span>
              </div>
              <OrderStatusPill order={order} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
