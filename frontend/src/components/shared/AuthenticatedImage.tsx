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
      if (!fetchSrc || !needsAuth || !accessToken) {
        return;
      }
      const fetchUrl: string = fetchSrc;

      const controller = new AbortController();
      let localObjectUrl: string | undefined;

      async function loadProtectedImage() {
        try {
          // Private uploads cannot be used as plain <img src> values because
          // the browser will not attach the bearer token automatically.
          const response = await fetch(fetchUrl, {
            headers: { Authorization: `Bearer ${accessToken}` },
            signal: controller.signal,
          });
          if (!response.ok) {
            throw new Error(`media request failed: ${response.status}`);
          }
          const contentType = response.headers.get("content-type")?.toLowerCase() || "";
          if (contentType && !contentType.startsWith("image/")) {
            throw new Error("media response is not an image");
          }
          const blob = await response.blob();
          if (blob.type && !blob.type.toLowerCase().startsWith("image/")) {
            throw new Error("media blob is not an image");
          }
          // The object URL gives <img> a local, revocable source after the
          // authenticated fetch has already enforced API authorization.
          localObjectUrl = URL.createObjectURL(blob);
          setObjectUrl(localObjectUrl);
        } catch {
          if (!controller.signal.aborted) {
            setFailed(true);
          }
        }
      }

      void loadProtectedImage();

      return () => {
        controller.abort();
        if (localObjectUrl) {
          // Revoke the fetch-local URL when the source changes to avoid keeping
          // private blobs alive longer than the component needs them.
          URL.revokeObjectURL(localObjectUrl);
        }
      };
    }, [accessToken, needsAuth, resolvedSrc]);

    React.useEffect(() => {
      return () => {
        if (objectUrl) {
          URL.revokeObjectURL(objectUrl);
        }
      };
    }, [objectUrl]);

    const imageSrc = needsAuth ? objectUrl : resolvedSrc;
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
