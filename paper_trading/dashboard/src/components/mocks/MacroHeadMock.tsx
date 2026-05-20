import { useMemo } from 'react'

interface Props {
  hovered?: boolean
}

const features = [
  { label: 'rate_diff', value: 0.82, highlighted: true },
  { label: '2y_yield_delta', value: 0.45, highlighted: false },
  { label: 'mom_63', value: 0.31, highlighted: false },
  { label: 'vs_spy', value: 0.18, highlighted: false },
]

export default function MacroHeadMock({ hovered }: Props) {
  const maxVal = Math.max(...features.map((f) => f.value))

  return (
    <div className="space-y-2">
      <div className="space-y-1.5">
        {features.map((f, i) => (
          <div key={f.label} className="flex items-center gap-2">
            <span className="text-[9px] text-gray-500 w-20 truncate">{f.label}</span>
            <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ease-out ${
                  f.highlighted ? 'bg-emerald-500' : 'bg-gray-500'
                }`}
                style={{
                  width: hovered ? `${(f.value / maxVal) * 100}%` : '0%',
                  transitionDelay: hovered ? `${i * 60}ms` : '0ms',
                }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="flex justify-center pt-1">
        <span className="px-2 py-0.5 rounded text-[9px] font-semibold bg-gray-800 text-gray-300 border border-gray-700">
          0.45 fixed weight
        </span>
      </div>
    </div>
  )
}
