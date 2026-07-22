// Minimal word-level LCS diff for side-by-side highlighting. Not on any hot
// path — failure cards render a handful at a time.

export type DiffPart = { text: string; kind: "same" | "add" | "del" };

function tokenize(s: string): string[] {
  return s.split(/(\s+)/).filter((t) => t.length > 0);
}

export function wordDiff(a: string, b: string): { left: DiffPart[]; right: DiffPart[] } {
  const A = tokenize(a);
  const B = tokenize(b);
  const n = A.length;
  const m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);

  const left: DiffPart[] = [];
  const right: DiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      left.push({ text: A[i], kind: "same" });
      right.push({ text: B[j], kind: "same" });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      left.push({ text: A[i], kind: "del" });
      i++;
    } else {
      right.push({ text: B[j], kind: "add" });
      j++;
    }
  }
  while (i < n) left.push({ text: A[i++], kind: "del" });
  while (j < m) right.push({ text: B[j++], kind: "add" });
  return { left, right };
}
