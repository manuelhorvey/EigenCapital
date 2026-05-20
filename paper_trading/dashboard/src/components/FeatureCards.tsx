import FeatureCard from './FeatureCard'
import RegimeMock from './mocks/RegimeMock'
import PortfolioMock from './mocks/PortfolioMock'
import WalkForwardMock from './mocks/WalkForwardMock'
import MacroHeadMock from './mocks/MacroHeadMock'
import BarrierMock from './mocks/BarrierMock'
import LiveMock from './mocks/LiveMock'

export default function FeatureCards() {
  return (
    <section className="bg-gray-950 px-6 py-24">
      <div className="max-w-6xl mx-auto">
        <h2 className="text-white text-2xl font-semibold text-center mb-12">
          Engineered for institutional-grade trading
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <FeatureCard
            title="Regime Detection"
            label="Hurst + ADX + vol regime classifier"
          >
            <RegimeMock />
          </FeatureCard>

          <FeatureCard
            title="Multi-Asset Portfolio"
            label="5 driver clusters · zero correlation"
          >
            <PortfolioMock />
          </FeatureCard>

          <FeatureCard
            title="Walk-Forward Validated"
            label="6/6 windows positive · bootstrap validated"
          >
            <WalkForwardMock />
          </FeatureCard>

          <FeatureCard
            title="Macro Expert Head"
            label="Protected macro signal · no feature drowning"
          >
            <MacroHeadMock />
          </FeatureCard>

          <FeatureCard
            title="Triple Barrier Labels"
            label="TP · SL · timeout · aligned with execution"
          >
            <BarrierMock />
          </FeatureCard>

          <FeatureCard
            title="Live Paper Trading"
            label="6 assets · 5 driver clusters · live"
          >
            <LiveMock />
          </FeatureCard>
        </div>
      </div>
    </section>
  )
}
