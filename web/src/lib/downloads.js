function normalizedRows(rows) {
  if (Array.isArray(rows)) {
    const headers = rows.length && typeof rows[0] === 'object' ? Object.keys(rows[0]) : [];
    return {
      headers,
      data: rows.map((row) => headers.map((header) => row[header])),
    };
  }
  return {
    headers: rows?.headers ?? [],
    data: rows?.data ?? [],
  };
}

function csvCell(value) {
  const text = value == null ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function tableRows(rows) {
  return normalizedRows(rows);
}

export function csvDataUrl(rows) {
  const table = normalizedRows(rows);
  const lines = [table.headers, ...table.data].map((row) => row.map(csvCell).join(','));
  return `data:text/csv;charset=utf-8,${encodeURIComponent(lines.join('\n'))}`;
}

export function jsonDataUrl(payload) {
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(payload, null, 2))}`;
}
