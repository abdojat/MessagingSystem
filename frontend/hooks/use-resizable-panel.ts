"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type ResizeMode = "growWithPointer" | "growOppositePointer";

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

type UseResizablePanelOptions = {
  initialWidth: number;
  minWidth: number;
  maxWidth: number;
  minRemainingWidth?: number;
  collapsedWidth?: number;
  collapseThreshold?: number;
  minExpandedWidth?: number;
  collapseOnThreshold?: boolean;
  storageKey?: string;
};

export function useResizablePanel({
  initialWidth,
  minWidth,
  maxWidth,
  minRemainingWidth = 360,
  collapsedWidth = 0,
  collapseThreshold = 80,
  minExpandedWidth,
  collapseOnThreshold = false,
  storageKey,
}: UseResizablePanelOptions) {
  const [width, setWidth] = useState(initialWidth);

  const cleanupRef = useRef<null | (() => void)>(null);
  const initializedFromStorageRef = useRef(false);
  const effectiveMinExpandedWidth = Math.max(minWidth, minExpandedWidth ?? minWidth);
  const lastExpandedWidthRef = useRef(Math.max(initialWidth, effectiveMinExpandedWidth));

  const getMaxWidth = useCallback(() => {
    if (typeof window === "undefined") return maxWidth;
    return Math.min(maxWidth, Math.max(minWidth, window.innerWidth - minRemainingWidth));
  }, [maxWidth, minWidth, minRemainingWidth]);

  const normalizeWidth = useCallback(
    (rawWidth: number) => {
      const max = getMaxWidth();
      if (!collapseOnThreshold) {
        return clamp(rawWidth, minWidth, max);
      }
      if (rawWidth <= collapseThreshold) {
        return collapsedWidth;
      }
      const expandedMin = Math.min(effectiveMinExpandedWidth, max);
      return clamp(rawWidth, expandedMin, max);
    },
    [collapseOnThreshold, collapseThreshold, collapsedWidth, effectiveMinExpandedWidth, getMaxWidth, minWidth],
  );

  useEffect(() => {
    if (!storageKey) {
      initializedFromStorageRef.current = true;
      return;
    }

    const stored = Number(window.localStorage.getItem(storageKey));
    const nextWidth = Number.isFinite(stored) ? normalizeWidth(stored) : normalizeWidth(initialWidth);
    const frame = window.requestAnimationFrame(() => {
      setWidth(nextWidth);
      initializedFromStorageRef.current = true;
    });

    return () => window.cancelAnimationFrame(frame);
  }, [initialWidth, normalizeWidth, storageKey]);

  useEffect(() => {
    const onResize = () => {
      setWidth((current) => normalizeWidth(current));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [normalizeWidth]);

  useEffect(() => {
    if (!storageKey || typeof window === "undefined") return;
    if (!initializedFromStorageRef.current) return;
    window.localStorage.setItem(storageKey, String(width));
  }, [storageKey, width]);

  useEffect(() => {
    if (collapseOnThreshold ? width > collapseThreshold : width > collapsedWidth) {
      lastExpandedWidthRef.current = width;
    }
  }, [collapseOnThreshold, collapseThreshold, collapsedWidth, width]);

  useEffect(() => {
    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
      }
    };
  }, []);

  const beginResize = useCallback(
    (event: React.MouseEvent<HTMLElement>, mode: ResizeMode) => {
      event.preventDefault();

      const startX = event.clientX;
      const startWidth = width;
      const multiplier = mode === "growWithPointer" ? 1 : -1;
      const previousCursor = document.body.style.cursor;
      const previousUserSelect = document.body.style.userSelect;

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const onMouseMove = (moveEvent: MouseEvent) => {
        const delta = (moveEvent.clientX - startX) * multiplier;
        if (collapseOnThreshold) {
          const nextWidth = clamp(startWidth + delta, collapsedWidth, getMaxWidth());
          setWidth(normalizeWidth(nextWidth));
          return;
        }
        const nextWidth = clamp(startWidth + delta, minWidth, getMaxWidth());
        setWidth(nextWidth);
      };

      const onMouseUp = () => {
        if (collapseOnThreshold) {
          setWidth((current) => normalizeWidth(current));
        } else {
          setWidth((current) => (current <= collapseThreshold ? collapsedWidth : current));
        }
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = previousCursor;
        document.body.style.userSelect = previousUserSelect;
        cleanupRef.current = null;
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);

      cleanupRef.current = onMouseUp;
    },
    [collapseOnThreshold, collapseThreshold, collapsedWidth, getMaxWidth, minWidth, normalizeWidth, width],
  );

  const isCollapsed = width <= collapsedWidth;
  const open = useCallback(() => {
    const max = getMaxWidth();
    if (collapseOnThreshold) {
      if (max <= collapseThreshold) {
        setWidth(collapsedWidth);
        return;
      }
      const expandedMin = Math.min(effectiveMinExpandedWidth, max);
      setWidth(clamp(lastExpandedWidthRef.current, expandedMin, max));
      return;
    }
    setWidth(clamp(lastExpandedWidthRef.current, minWidth, max));
  }, [collapseOnThreshold, collapseThreshold, collapsedWidth, effectiveMinExpandedWidth, getMaxWidth, minWidth]);
  const close = useCallback(() => {
    setWidth(collapsedWidth);
  }, [collapsedWidth]);

  return { width, isCollapsed, beginResize, open, close };
}
