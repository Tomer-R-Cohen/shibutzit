"use client";

import { useState } from "react";
import {
  ColumnDef,
  SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Button } from "@/components/ui/primitives";

export function buildColumns(rows: Record<string, unknown>[]): ColumnDef<Record<string, unknown>>[] {
  if (rows.length === 0) return [];
  return Object.keys(rows[0]).map((key) => ({
    accessorKey: key,
    header: key,
    cell: (info) => formatVal(info.getValue()),
  }));
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "כן" : "לא";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const columns = buildColumns(rows);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 20 } },
  });

  if (rows.length === 0) return <p className="p-4 text-sm text-[var(--cw-ink-3)]">אין נתונים להצגה</p>;

  return (
    <div>
      <input
        placeholder="חיפוש"
        value={globalFilter}
        onChange={(e) => table.setGlobalFilter(e.target.value)}
        className="mb-3 w-full max-w-xs border-b border-[var(--cw-line)] bg-transparent px-1 py-1.5 text-sm focus:border-[var(--cw-accent)] focus:outline-none"
      />
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full min-w-max text-right text-sm">
          <thead className="sticky top-0 bg-white">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    onClick={h.column.getToggleSortingHandler()}
                    className="cursor-pointer whitespace-nowrap border-b border-[var(--cw-line)] px-3 py-2 font-medium text-[var(--cw-ink-2)] select-none"
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-[var(--cw-line-2)]">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-[var(--cw-panel)]">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="whitespace-nowrap px-3 py-1.5 text-[var(--cw-ink)]">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-2 text-sm">
        <Button size="sm" variant="secondary" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>
          הקודם
        </Button>
        <span>
          עמוד {table.getState().pagination.pageIndex + 1} מתוך {table.getPageCount()}
        </span>
        <Button size="sm" variant="secondary" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>
          הבא
        </Button>
      </div>
    </div>
  );
}
