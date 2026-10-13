function encodeRecordCursor(record) {
  if (!record || typeof record.createdAt !== 'string' || typeof record._id !== 'string') return null;
  return Buffer.from(JSON.stringify({ createdAt: record.createdAt, _id: record._id }), 'utf8').toString('base64url');
}

function decodeRecordCursor(value) {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value !== 'string' || value.length > 300) throw new Error('历史游标无效。');
  try {
    const cursor = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'));
    if (!cursor || typeof cursor.createdAt !== 'string' || Number.isNaN(Date.parse(cursor.createdAt)) || typeof cursor._id !== 'string' || cursor._id.length === 0) throw new Error('invalid');
    return { createdAt: cursor.createdAt, _id: cursor._id };
  } catch {
    throw new Error('历史游标无效。');
  }
}

function recordCursorWhere(command, coupleId, cursor) {
  if (!cursor) return { coupleId };
  return command.or([
    { coupleId, createdAt: command.lt(cursor.createdAt) },
    { coupleId, createdAt: cursor.createdAt, _id: command.lt(cursor._id) },
  ]);
}

function exportCursorWhere(command, filters, timestampField, snapshotAt, cursor) {
  if (!cursor) return { ...filters, [timestampField]: command.lte(snapshotAt) };
  return command.or([
    { ...filters, [timestampField]: command.lt(cursor.timestamp) },
    { ...filters, [timestampField]: cursor.timestamp, _id: command.lt(cursor._id) },
  ]);
}

function nextExportCursor(record, timestampField) {
  if (!record || typeof record._id !== 'string' || typeof record[timestampField] !== 'string') throw new Error('导出数据缺少稳定分页字段。');
  return { timestamp: record[timestampField], _id: record._id };
}

module.exports = { decodeRecordCursor, encodeRecordCursor, recordCursorWhere, exportCursorWhere, nextExportCursor };
