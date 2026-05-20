interface Props {
  onClick: () => void
}

export default function EnterButton({ onClick }: Props) {
  return (
    <section className="bg-gray-950 px-6 pb-32">
      <div className="max-w-6xl mx-auto flex justify-center">
        <button
          onClick={onClick}
          className="px-8 py-3 rounded-xl text-white font-medium text-sm border border-gray-700 bg-transparent hover:bg-gray-900 hover:border-gray-500 transition-all duration-300"
        >
          Enter Dashboard →
        </button>
      </div>
    </section>
  )
}
