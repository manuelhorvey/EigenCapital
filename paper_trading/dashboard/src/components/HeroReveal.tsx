import { useLerpMouse } from '../hooks/useLerpMouse'

interface Props {
  children?: React.ReactNode
}

export default function HeroReveal({ children }: Props) {
  const { ref, onMouseMove, onMouseLeave } = useLerpMouse()

  return (
    <div
      ref={ref}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      className="relative w-full h-screen overflow-hidden bg-gray-950 select-none"
      style={{
        maskImage: `radial-gradient(circle 180px at var(--mx) var(--my), transparent 0%, transparent 40%, black 100%)`,
        WebkitMaskImage: `radial-gradient(circle 180px at var(--mx) var(--my), transparent 0%, transparent 40%, black 100%)`,
      }}
    >
      <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
        <h1 className="text-white text-[72px] font-[500] tracking-tight">QuantForge</h1>
        <p className="text-gray-400 text-xl mt-2">Macro-driven. Regime-aware.</p>
      </div>

      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 text-gray-600 text-xs pointer-events-none z-10">
        Move cursor to explore
      </div>

      {children}
    </div>
  )
}
