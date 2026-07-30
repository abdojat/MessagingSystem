"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const PAGE_SIZES = [10, 25, 50, 100];

interface AdminTablePaginationProps {
  offset: number;
  pageSize: number;
  total: number;
  onOffsetChange: (offset: number) => void;
  onPageSizeChange: (size: number) => void;
}

export function AdminTablePagination({
  offset,
  pageSize,
  total,
  onOffsetChange,
  onPageSizeChange,
}: AdminTablePaginationProps) {
  const t = useTranslations("superadmin.pagination");
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(pageCount, Math.floor(offset / pageSize) + 1);
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + pageSize, total);

  useEffect(() => {
    if (offset < total || offset === 0) return;
    const lastValidOffset = total === 0 ? 0 : Math.floor((total - 1) / pageSize) * pageSize;
    onOffsetChange(lastValidOffset);
  }, [offset, onOffsetChange, pageSize, total]);

  return (
    <div className="flex flex-col gap-3 border-t p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{t("rowsPerPage")}</span>
        <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
          <SelectTrigger className="w-20" aria-label={t("rowsPerPage")}><SelectValue /></SelectTrigger>
          <SelectContent>{PAGE_SIZES.map((size) => <SelectItem key={size} value={String(size)}>{size}</SelectItem>)}</SelectContent>
        </Select>
        <span className="hidden sm:inline">{t("range", { first, last, total })}</span>
      </div>
      <div className="flex items-center justify-between gap-2 sm:justify-end">
        <span className="text-sm text-muted-foreground">{t("page", { page: currentPage, pages: pageCount })}</span>
        <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}>{t("previous")}</Button>
        <Button variant="outline" size="sm" disabled={offset + pageSize >= total} onClick={() => onOffsetChange(offset + pageSize)}>{t("next")}</Button>
      </div>
    </div>
  );
}
