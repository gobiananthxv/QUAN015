import { describePeriod, presetsFor, samePeriod, usePeriod } from '../period'

/**
 * The one control that sets the analysis period for the whole platform.
 *
 * Lives beside the data-freshness line rather than inside any tab, because it
 * is not a property of a chart — it is the question every tab is answering.
 */
export function PeriodBar() {
  const { period, setPeriod, bounds, restricted } = usePeriod()
  const presets = presetsFor(bounds)

  return (
    <div className="periodbar">
      <div className="periodbar-left">
        <span className="presets-label">Period</span>
        {presets.map((p) => (
          <button
            key={p.label}
            className={`chip${samePeriod(p.period, period) ? ' active' : ''}`}
            onClick={() => setPeriod(p.period)}
          >
            {p.label}
          </button>
        ))}
        <label className="inline-date">
          from
          <input
            type="date"
            min={bounds.start}
            max={bounds.end}
            value={period.start ?? ''}
            onChange={(e) => setPeriod({ ...period, start: e.target.value || undefined })}
          />
        </label>
        <label className="inline-date">
          to
          <input
            type="date"
            min={bounds.start}
            max={bounds.end}
            value={period.end ?? ''}
            onChange={(e) => setPeriod({ ...period, end: e.target.value || undefined })}
          />
        </label>
      </div>

      <div className="periodbar-right">
        <span className={restricted ? 'period-active' : 'period-full'}>
          {describePeriod(period, bounds)}
        </span>
        {restricted && (
          <button className="chip reset" onClick={() => setPeriod({})}>
            ✕ full history
          </button>
        )}
      </div>
    </div>
  )
}
