/**
 * PR #412, front end half.  src/pages/SurveyList.tsx
 * Same PR as review_this.py. Assume Survey, Row, apiBase and the router all exist.
 */

import { useEffect, useState } from "react";

type Survey = {
  id: number;
  name: string;
  description: string;
  responseCount: number;
  completionRate: number;
  status: "open" | "closed";
};

export function SurveyList({ orgId }: { orgId: string }) {
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch(`/api/surveys?org=${orgId}&q=${query}`)
      .then((r) => r.json())
      .then((data) => setSurveys(data));
  }, []);

  const totalResponses = surveys.reduce((sum, s) => sum + s.responseCount, 0);
  const avgCompletion =
    surveys.reduce((sum, s) => sum + s.completionRate, 0) / surveys.length;

  const handleDelete = (id: number) => {
    fetch(`/api/surveys/${id}`, { method: "DELETE" });
    setSurveys(surveys.filter((s) => s.id !== id));
  };

  return (
    <div className="p-6">
      <input
        className="border rounded px-3 py-2"
        placeholder="Search surveys"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <div className="mt-4 flex gap-8">
        <span>Total responses: {totalResponses}</span>
        <span>Average completion: {avgCompletion.toFixed(1)}%</span>
      </div>

      <div
        className="prose mt-4"
        dangerouslySetInnerHTML={{ __html: surveys[0]?.description }}
      />

      <table className="mt-6 w-full">
        <tbody>
          {surveys
            .filter((s) => s.name.toLowerCase().includes(query.toLowerCase()))
            .map((s, i) => (
              <tr key={i}>
                <td>{s.name}</td>
                <td>{s.responseCount}</td>
                <td>{s.completionRate}%</td>
                <td>
                  <button onClick={() => handleDelete(s.id)}>Delete</button>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
