/**
 * AML flag badge — clean state, count of flags, or hard-blocked.
 */

export function AmlFlagBadge({ amlResult, onOpen }) {
  const flagCount = amlResult?.flag_count ?? 0;
  const hardBlock = !!amlResult?.hard_block_required;

  if (!amlResult || flagCount === 0) {
    return <span className="finoks-aml finoks-aml--clean">✓ AML Clean</span>;
  }
  const label = hardBlock
    ? `HARD BLOCKED · ${flagCount} flag${flagCount > 1 ? "s" : ""}`
    : `${flagCount} flag${flagCount > 1 ? "s" : ""}`;
  return (
    <button
      type="button"
      className={`finoks-aml ${hardBlock ? "finoks-aml--hard" : "finoks-aml--warn"}`}
      onClick={onOpen}
      title={amlResult?.human_review_note || ""}
    >
      ⚠ {label}
    </button>
  );
}
