import * as React from "react"
import { AuthenticatedImage } from "@/components/shared/AuthenticatedImage"
import { cn } from "./button"

const Avatar = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full", className)}
      {...props}
    />
  )
)
Avatar.displayName = "Avatar"

const AvatarImage = React.forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, src, onError, ...props }, ref) => {
    const imageSrc = typeof src === "string" ? src : undefined
    const [error, setError] = React.useState(false)
    React.useEffect(() => setError(false), [imageSrc])
    if (!imageSrc || error) return null
    return (
      <AuthenticatedImage
        ref={ref}
        src={imageSrc}
        onError={(event) => {
          setError(true)
          onError?.(event)
        }}
        className={cn("aspect-square h-full w-full object-cover", className)}
        {...props}
      />
    )
  }
)
AvatarImage.displayName = "AvatarImage"

const AvatarFallback = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex h-full w-full items-center justify-center rounded-full bg-muted", className)}
      {...props}
    />
  )
)
AvatarFallback.displayName = "AvatarFallback"

export { Avatar, AvatarImage, AvatarFallback }
