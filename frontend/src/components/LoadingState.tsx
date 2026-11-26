export default function LoadingState() {
  return (
    <div aria-busy="true" aria-live="polite">
      <p className="mb-4 text-sm text-slate-400">
        Finding routes and checking the forecast at each checkpoint. This usually takes a few seconds…
      </p>
      <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-64 animate-pulse rounded-2xl border border-slate-800 bg-slate-900/60" />
        ))}
      </div>
    </div>
  )
}