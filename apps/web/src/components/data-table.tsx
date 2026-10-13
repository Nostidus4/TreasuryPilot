import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    align?: 'left' | 'right';
    /** Hide the column below the `md` breakpoint. */
    hideOnMobile?: boolean;
  }
}

export interface FilterOption {
  value: string;
  label: string;
  count?: number;
}

/**
 * The one table of the app: sticky header, sortable columns, search,
 * quick-filter chips, keyboard-activatable rows and a meaningful empty state.
 */
export function DataTable<Row>({
  columns,
  data,
  empty,
  filter,
  getRowId,
  onRowClick,
  rowLabel,
  searchPlaceholder,
  selectedId,
  toolbar,
}: {
  columns: Array<ColumnDef<Row, unknown>>;
  data: Row[];
  empty: ReactNode;
  filter?: {
    options: FilterOption[];
    value: string;
    onChange: (value: string) => void;
  };
  getRowId: (row: Row) => string;
  onRowClick?: (row: Row) => void;
  /** Accessible name of a row, used when rows are clickable. */
  rowLabel?: (row: Row) => string;
  searchPlaceholder?: string;
  selectedId?: string;
  toolbar?: ReactNode;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [search, setSearch] = useState('');
  const table = useReactTable({
    data,
    columns,
    getRowId,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
  const rows = table.getRowModel().rows;

  return (
    <div>
      {(searchPlaceholder || filter || toolbar) && (
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
          {searchPlaceholder && (
            <div className="relative w-full sm:w-64">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground"
                aria-hidden="true"
              />
              <Input
                type="search"
                aria-label={searchPlaceholder}
                placeholder={searchPlaceholder}
                className="h-8 pl-8"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          )}
          {filter && (
            <div
              className="flex flex-wrap gap-1"
              role="group"
              aria-label={t('Filter')}
            >
              {filter.options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={filter.value === option.value}
                  onClick={() => filter.onChange(option.value)}
                  className={cn(
                    'inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-sm transition-colors',
                    filter.value === option.value
                      ? 'border-primary bg-primary-muted font-medium text-foreground'
                      : 'border-border bg-surface text-muted-foreground hover:bg-surface-muted',
                  )}
                >
                  {option.label}
                  {option.count !== undefined && (
                    <span className="num text-xs text-subtle-foreground">
                      {option.count}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
          {toolbar && <div className="ml-auto flex gap-2">{toolbar}</div>}
        </div>
      )}

      {rows.length === 0 ? (
        empty
      ) : (
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const meta = header.column.columnDef.meta;
                  const sorted = header.column.getIsSorted();
                  const label = flexRender(
                    header.column.columnDef.header,
                    header.getContext(),
                  );
                  return (
                    <TableHead
                      key={header.id}
                      align={meta?.align}
                      aria-sort={
                        sorted === 'asc'
                          ? 'ascending'
                          : sorted === 'desc'
                            ? 'descending'
                            : undefined
                      }
                      className={cn(
                        meta?.hideOnMobile && 'hidden md:table-cell',
                      )}
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            'inline-flex items-center gap-1 hover:text-foreground',
                            meta?.align === 'right' && 'flex-row-reverse',
                          )}
                        >
                          {label}
                          {sorted === 'asc' ? (
                            <ArrowUp className="size-3" aria-hidden="true" />
                          ) : sorted === 'desc' ? (
                            <ArrowDown className="size-3" aria-hidden="true" />
                          ) : (
                            <ChevronsUpDown
                              className="size-3 opacity-50"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                      ) : (
                        label
                      )}
                    </TableHead>
                  );
                })}
              </tr>
            ))}
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.id}
                data-clickable={onRowClick ? true : undefined}
                data-selected={row.id === selectedId ? true : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                aria-label={onRowClick ? rowLabel?.(row.original) : undefined}
                onClick={
                  onRowClick ? () => onRowClick(row.original) : undefined
                }
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (
                          event.key === 'Enter' &&
                          event.target === event.currentTarget
                        ) {
                          onRowClick(row.original);
                        }
                      }
                    : undefined
                }
              >
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta;
                  return (
                    <TableCell
                      key={cell.id}
                      align={meta?.align}
                      className={cn(
                        meta?.hideOnMobile && 'hidden md:table-cell',
                      )}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
