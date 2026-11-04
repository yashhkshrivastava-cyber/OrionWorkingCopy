import { useEffect, useState } from 'react'

const SIZES = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-20 w-20 text-xl',
  /** the size of a row in a list of people, and of a conversation's header */
  row: 'h-12 w-12 text-base',
  xl: 'h-14 w-14 text-lg',
}

const ROLE_TONE: Record<string, string> = {
  admin: 'bg-primary text-on-primary',
  editor: 'bg-violet text-[color:var(--color-bg)]',
  viewer: 'bg-[color:var(--color-text-faint)] text-[color:var(--color-bg)]',
}

type AvatarUser = {
  id: number
  display_name: string
  role?: string
  has_avatar?: boolean
  avatar_version?: number
  avatar_url?: string | null
}

function photoSrc(user: AvatarUser): string {
  if (user.avatar_url) return user.avatar_url
  return `/api/media/avatars/${user.id}.jpg?v=${user.avatar_version || 1}`
}

export function UserAvatar({
  user,
  size = 'md',
  className = '',
}: {
  user: AvatarUser
  size?: keyof typeof SIZES
  className?: string
}) {
  const [broken, setBroken] = useState(false)
  const src = photoSrc(user)
  useEffect(() => {
    setBroken(false)
  }, [src])
  const showPhoto = !broken
  const initial = (user.display_name?.trim()[0] || '?').toUpperCase()

  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold ${SIZES[size]} ${
        showPhoto ? 'bg-muted' : ROLE_TONE[user.role || 'viewer'] || ROLE_TONE.viewer
      } ${className}`}
      aria-hidden
    >
      {showPhoto ? (
        <img
          key={src}
          src={src}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : (
        initial
      )}
    </span>
  )
}
