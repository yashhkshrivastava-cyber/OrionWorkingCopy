const EMOJIS = [
  '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣',
  '😊', '😇', '🙂', '😉', '😍', '🥰', '😘', '😋',
  '😜', '🤪', '🤗', '🤔', '😐', '😴', '😷', '🤒',
  '😎', '🤩', '🥳', '😤', '😭', '😡', '🤯', '🥶',
  '👍', '👎', '👏', '🙌', '🤝', '🙏', '💪', '✌️',
  '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍',
  '🔥', '⭐', '✨', '🎉', '🎊', '✅', '❌', '⚠️',
  '📌', '📎', '📷', '🎥', '📁', '📝', '📞', '💡',
  '☕', '🍕', '🎂', '🏠', '🚗', '✈️', '☀️', '🌧️',
]

export function EmojiPicker({
  onPick,
}: {
  onPick: (emoji: string) => void
}) {
  return (
    <div className="absolute bottom-full left-0 z-20 mb-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl border border-[color:var(--color-border)] bg-surface p-2 shadow-overlay">
      <div className="grid grid-cols-8 gap-0.5">
        {EMOJIS.map((emoji) => (
          <button
            key={emoji}
            type="button"
            onClick={() => onPick(emoji)}
            className="flex h-8 items-center justify-center rounded-md text-lg hover:bg-muted"
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  )
}
