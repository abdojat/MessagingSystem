"use client";

import * as React from "react";

import { isProtectedApiMediaUrl, resolveApiMediaUrl } from "@/lib/mediaUrl";
import { useAuthStore } from "@/store/authStore";

export type AuthenticatedImageProps = Omit<React.ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src?: string | null;
};

const AuthenticatedImage = React.forwardRef<HTMLImageElement, AuthenticatedImageProps>(
  ({ src, onError, ...props }, ref) => {
    const accessToken = useAuthStore((state) => state.accessToken);
    const resolvedSrc = React.useMemo(() => resolveApiMediaUrl(src), [src]);
    const needsAuth = React.useMemo(() => isProtectedApiMediaUrl(resolvedSrc), [resolvedSrc]);
    const [objectUrl, setObjectUrl] = React.useState<string | undefined>();
    const [failed, setFailed] = React.useState(false);

    React.useEffect(() => {
      setFailed(false);
      setObjectUrl(undefined);
    }, [resolvedSrc, needsAuth, accessToken]);

    React.useEffect(() => {
      const fetchSrc = resolvedSrc;
      // Return early when `!fetchSrc || !needsAuth || !accessToken` because the remaining work is not applicable.
      if (!fetchSrc || !needsAuth || !accessToken) {
        return;
      }
      const fetchUrl: string = fetchSrc;

      const controller = new AbortController();
      let localObjectUrl: string | undefined;

      // Loads protected image; parent React views use it to render or control the interface.
      async function loadProtectedImage() {
        // Attempt this operation and recover from expected failures in the catch block below.
        try {
          const response = await fetch(fetchUrl, {
            headers: { Authorization: `Bearer ${accessToken}` },
            signal: controller.signal,
          });
          // Reject this path when `!response.ok` to prevent invalid state from progressing.
          if (!response.ok) {
            throw new Error(`media request failed: ${response.status}`);
          }
          const contentType = response.headers.get("content-type")?.toLowerCase() || "";
          // Reject this path when `contentType && !contentType.startsWith("image/")` to prevent invalid state from progressing.
          if (contentType && !contentType.startsWith("image/")) {
            throw new Error("media response is not an image");
          }
          const blob = await response.blob();
          // Reject this path when `blob.type && !blob.type.toLowerCase().startsWith("image/")` to prevent invalid state from progressing.
          if (blob.type && !blob.type.toLowerCase().startsWith("image/")) {
            throw new Error("media blob is not an image");
          }
          localObjectUrl = URL.createObjectURL(blob);
          setObjectUrl(localObjectUrl);
        // Recover from the attempted operation by applying this error-handling path.
        } catch {
          // Run this conditional step only when `!controller.signal.aborted` is true.
          if (!controller.signal.aborted) {
            setFailed(true);
          }
        }
      }

      void loadProtectedImage();

      return () => {
        controller.abort();
        // Run this conditional step only when `localObjectUrl` is true.
        if (localObjectUrl) {
          URL.revokeObjectURL(localObjectUrl);
        }
      };
    }, [accessToken, needsAuth, resolvedSrc]);

    React.useEffect(() => {
      return () => {
        // Run this conditional step only when `objectUrl` is true.
        if (objectUrl) {
          URL.revokeObjectURL(objectUrl);
        }
      };
    }, [objectUrl]);

    const imageSrc = needsAuth ? objectUrl : resolvedSrc;
    // Return early when `!imageSrc || failed` because the remaining work is not applicable.
    if (!imageSrc || failed) {
      return null;
    }

    return (
      <img
        ref={ref}
        src={imageSrc}
        onError={onError}
        {...props}
      />
    );
  },
);
AuthenticatedImage.displayName = "AuthenticatedImage";

export { AuthenticatedImage };
