const isNum = (n) => typeof n === 'number' && Number.isFinite(n)

/**
 * Horizontal gauge showing where a value sits against its reference bands.
 *
 * Zones are derived from the same bounds the backend classified against, so the
 * colour under the marker always agrees with the badge. Where a critical bound
 * is null the marker cannot escalate past warning in that direction, and the
 * gauge shows amber running to the edge rather than inventing a red zone.
 */
export default function RangeGauge({ value, unit, reference }) {
  const ref = reference || {}
  const nl = isNum(ref.normal_low) ? ref.normal_low : null
  const nh = isNum(ref.normal_high) ? ref.normal_high : null
  const cl = isNum(ref.critical_low) ? ref.critical_low : null
  const ch = isNum(ref.critical_high) ? ref.critical_high : null
  const val = isNum(value) ? value : null

  if (nl === null || nh === null) {
    return (
      <div className="gauge-empty">
        No reference range available — this result was not scored against a band.
      </div>
    )
  }

  const points = [nl, nh, cl, ch, val].filter(isNum)
  let lo = Math.min(...points)
  let hi = Math.max(...points)
  const span = hi - lo || Math.abs(hi) || 1
  lo -= span * 0.12
  hi += span * 0.12

  const pct = (x) => Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100))
  const seg = (from, to) => ({ left: `${pct(from)}%`, width: `${pct(to) - pct(from)}%` })

  const zones = []
  if (cl !== null) {
    zones.push({ key: 'cl', cls: 'zone-critical', style: seg(lo, cl) })
    zones.push({ key: 'wl', cls: 'zone-warning', style: seg(cl, nl) })
  } else {
    zones.push({ key: 'wl', cls: 'zone-warning', style: seg(lo, nl) })
  }
  zones.push({ key: 'n', cls: 'zone-normal', style: seg(nl, nh) })
  if (ch !== null) {
    zones.push({ key: 'wh', cls: 'zone-warning', style: seg(nh, ch) })
    zones.push({ key: 'chz', cls: 'zone-critical', style: seg(ch, hi) })
  } else {
    zones.push({ key: 'wh', cls: 'zone-warning', style: seg(nh, hi) })
  }

  // Tick labels collide when two bounds sit close together (e.g. glucose
  // crit-low 54 against normal-low 70). Lay them out greedily across two rows
  // so a crowded gauge stays readable instead of overprinting.
  const MIN_SEPARATION = 16
  const rowLast = [-Infinity, -Infinity]
  const ticks = [
    cl !== null && { at: cl, label: `crit ${cl}` },
    { at: nl, label: `${nl}` },
    { at: nh, label: `${nh}` },
    ch !== null && { at: ch, label: `crit ${ch}` },
  ]
    .filter(Boolean)
    .sort((a, b) => a.at - b.at)
    .map((t) => {
      const pos = pct(t.at)
      const row = pos - rowLast[0] > MIN_SEPARATION ? 0 : 1
      rowLast[row] = pos
      return { ...t, pos, row }
    })
  const scaleRows = ticks.some((t) => t.row === 1) ? 2 : 1

  // Keep the value label inside the track when the marker sits at an edge.
  const markerShift = (p) => (p > 88 ? '-85%' : p < 12 ? '-15%' : '-50%')

  return (
    <div className="gauge">
      <div className="gauge-track">
        {zones.map((z) => (
          <div key={z.key} className={`gauge-zone ${z.cls}`} style={z.style} />
        ))}
        {ticks.map((t, i) => (
          <div key={i} className="gauge-tick" style={{ left: `${t.pos}%` }} />
        ))}
        {val !== null && (
          <div className="gauge-marker" style={{ left: `${pct(val)}%` }}>
            <div className="gauge-marker-line" />
            <div
              className="gauge-marker-label"
              style={{ transform: `translateX(${markerShift(pct(val))})` }}
            >
              {val}
              {unit ? ` ${unit}` : ''}
            </div>
          </div>
        )}
      </div>
      <div className="gauge-scale" style={{ height: `${scaleRows * 14}px` }}>
        {ticks.map((t, i) => (
          <span
            key={i}
            className="gauge-tick-label"
            style={{ left: `${t.pos}%`, top: `${t.row * 13}px` }}
          >
            {t.label}
          </span>
        ))}
      </div>
      <div className="gauge-legend">
        <span><i className="swatch zone-normal" /> normal band {nl}–{nh}{unit ? ` ${unit}` : ''}</span>
        <span><i className="swatch zone-warning" /> outside normal</span>
        {(cl !== null || ch !== null) && (
          <span><i className="swatch zone-critical" /> critical</span>
        )}
      </div>
    </div>
  )
}
