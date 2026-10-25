import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { describeFinancial, type ExtractedMemory, type ExtractionOutput } from "@/lib/extraction";
import { formatPercent } from "@/lib/format";

function MemoryRow({ memory, index }: { memory: ExtractedMemory; index: number }) {
  return (
    <TableRow>
      <TableCell className="align-top font-mono text-xs text-muted-foreground">{index}</TableCell>
      <TableCell className="align-top">
        <Badge variant="secondary" className="font-normal">
          {memory.memory_type.replace(/_/g, " ")}
        </Badge>
        {memory.state !== "not_applicable" && (
          <div className="mt-1">
            <StatusBadge status={memory.state} />
          </div>
        )}
        <div className="tabular mt-1 text-xs text-muted-foreground">
          {formatPercent(memory.confidence)} sure
        </div>
      </TableCell>
      <TableCell className="whitespace-normal align-top">
        <div className="text-sm">{memory.content}</div>
        {memory.ambiguity && (
          <div className="mt-1 text-xs text-warning">Unclear: {memory.ambiguity}</div>
        )}
        {memory.sensitivity === "sensitive" && (
          <div className="mt-1 text-xs text-muted-foreground">Marked sensitive</div>
        )}
      </TableCell>
      <TableCell className="whitespace-normal align-top">
        {memory.evidence.map((item, position) => (
          <span key={position} className="block text-xs text-muted-foreground">
            <span className="font-mono">[{item.message_index}]</span> “{item.quote}”
          </span>
        ))}
      </TableCell>
      <TableCell className="whitespace-normal align-top text-xs">
        {memory.temporal && (
          <div>
            <span className="text-muted-foreground">time </span>
            {memory.temporal.expression}
            {memory.temporal.resolved_date && <span> = {memory.temporal.resolved_date}</span>}
          </div>
        )}
        {memory.financial && (
          <div>
            <span className="text-muted-foreground">money </span>
            {describeFinancial(memory.financial)}
          </div>
        )}
        {!memory.temporal && !memory.financial && (
          <span className="text-muted-foreground">none</span>
        )}
      </TableCell>
    </TableRow>
  );
}

/** A whole extraction: the disposition, every memory, and the names it found. */
export function ExtractionView({ output }: { output: ExtractionOutput }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={output.disposition} />
        <span className="text-muted-foreground">{output.disposition_reason}</span>
      </div>
      {output.memories.length === 0 ? (
        <p className="text-sm text-muted-foreground">No memories were produced.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">#</TableHead>
              <TableHead className="w-32">Type</TableHead>
              <TableHead>Content</TableHead>
              <TableHead className="w-44">Evidence</TableHead>
              <TableHead className="w-40">Time and money</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {output.memories.map((memory, index) => (
              <MemoryRow key={index} memory={memory} index={index} />
            ))}
          </TableBody>
        </Table>
      )}
      {output.entity_mentions.length > 0 && (
        <div className="text-xs">
          <span className="text-muted-foreground">Names found: </span>
          {output.entity_mentions.map((mention, index) => (
            <span key={index} className="mr-3 inline-flex items-center gap-1">
              <span className="font-medium">{mention.mention_text}</span>
              <span className="text-muted-foreground">
                {mention.entity_type}, message {mention.message_index}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
