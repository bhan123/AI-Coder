async function executeMutationInTransaction({ transaction, previousResult, beforeWorker, worker, addAudit, saveIdempotency }) {
  const previous = await previousResult(transaction);
  if (previous && previous.found === true) return previous.value;
  if (beforeWorker) await beforeWorker(transaction);
  const outcome = await worker(transaction);
  const data = outcome.data === undefined ? null : outcome.data;
  await addAudit(transaction, outcome);
  await saveIdempotency(transaction, data);
  return data;
}

async function withCachedMutationEnvelope({ loadCached, execute }) {
  const cached = await loadCached();
  if (cached && cached.found === true) return { ok: true, data: cached.value };
  return execute();
}

module.exports = { executeMutationInTransaction, withCachedMutationEnvelope };
