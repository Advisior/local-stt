import SwiftUI

struct HistoryEntry: Identifiable {
    var id: String { timestamp + text.prefix(40) }
    let timestamp: String
    let text: String
    let durationS: Double
    let db: Double
}

struct HistoryView: View {
    @ObservedObject var config: ConfigManager
    var onDismiss: () -> Void

    @State private var entries: [HistoryEntry] = []
    @State private var pauseRefresh = false
    private let refreshTimer = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Transcript History")
                    .font(.headline)
                Spacer()
                Button("Close") { onDismiss() }
                    .buttonStyle(.plain)
                    .foregroundColor(.secondary)
            }
            .padding()

            Divider()

            if entries.isEmpty {
                Spacer()
                Text("No transcriptions yet.")
                    .foregroundColor(.secondary)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(entries) { entry in
                            EntryCard(
                                entry: entry,
                                corrections: config.corrections,
                                pauseRefresh: $pauseRefresh,
                                onSaveCorrection: { wrong, right in
                                    config.addCorrection(wrong: wrong, right: right)
                                }
                            )
                        }
                    }
                    .padding()
                }
            }
        }
        .frame(width: 560, height: 480)
        .onAppear { loadHistory() }
        .onReceive(refreshTimer) { _ in if !pauseRefresh { loadHistory() } }
    }

    private func loadHistory() {
        let historyURL = ConfigManager.configDir.appendingPathComponent("history.jsonl")
        guard let content = try? String(contentsOf: historyURL) else { return }
        let lines = content.split(separator: "\n", omittingEmptySubsequences: true)
        let newEntries: [HistoryEntry] = lines.compactMap { line -> HistoryEntry? in
            guard let data = line.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let text = json["text"] as? String,
                  let timestamp = json["timestamp"] as? String
            else { return nil }
            return HistoryEntry(
                timestamp: timestamp,
                text: text,
                durationS: json["duration_s"] as? Double ?? 0,
                db: json["db"] as? Double ?? 0
            )
        }.reversed()
        // Only update if data actually changed — avoids resetting scroll position
        if newEntries.map(\.id) != entries.map(\.id) {
            entries = newEntries
        }
    }
}

struct WordToken: View {
    let index: Int
    let word: String
    let cleanWord: String
    let isCorrected: Bool
    let isSelected: Bool
    let corrections: [String: String]
    var onTap: (Int) -> Void

    var body: some View {
        Button(action: {
            onTap(index)
        }) {
            Text(word)
                .padding(.horizontal, 5)
                .padding(.vertical, 2)
                .background(
                    isSelected ? Color.blue.opacity(0.3) :
                    isCorrected ? Color.orange.opacity(0.2) :
                    Color.secondary.opacity(0.08)
                )
                .foregroundColor(
                    isSelected ? .blue :
                    isCorrected ? .orange :
                    .primary
                )
                .cornerRadius(4)
                .overlay(
                    isSelected ?
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(Color.blue.opacity(0.5), lineWidth: 1) :
                    nil
                )
        }
        .buttonStyle(.plain)
    }
}

struct EntryCard: View {
    let entry: HistoryEntry
    let corrections: [String: String]
    @Binding var pauseRefresh: Bool
    var onSaveCorrection: (String, String) -> Void

    @State private var selectedRange: ClosedRange<Int>? = nil
    @State private var showPopover = false
    @State private var correctionText: String = ""
    @State private var popoverAnchorIndex: Int = 0
    @State private var copied = false

    private var words: [String] {
        entry.text.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
    }

    private var selectedPhrase: String {
        guard let range = selectedRange else { return "" }
        let cleanWords = words[range].map { $0.trimmingCharacters(in: .punctuationCharacters) }
        return cleanWords.joined(separator: " ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Timestamp + meta + copy button
            HStack(spacing: 8) {
                Text(entry.timestamp)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text(String(format: "%.1fs", entry.durationS))
                    .font(.caption)
                    .foregroundColor(.secondary)
                if let range = selectedRange {
                    if range.count > 1 {
                        Text("\(range.count) words — tap selection to correct")
                            .font(.caption)
                            .foregroundColor(.blue)
                    } else {
                        Text("tap another word to extend, or tap again to correct")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    Button(action: { selectedRange = nil }) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundColor(.secondary)
                            .font(.caption)
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                Button(action: {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(entry.text, forType: .string)
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        copied = false
                    }
                }) {
                    HStack(spacing: 3) {
                        Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        if copied {
                            Text("Copied")
                                .font(.caption2)
                        }
                    }
                    .foregroundColor(copied ? .green : .secondary)
                    .font(.caption)
                }
                .buttonStyle(.plain)
            }

            // Words as clickable tokens
            FlowLayout(spacing: 4) {
                ForEach(Array(words.enumerated()), id: \.offset) { index, word in
                    let cleanWord = word.trimmingCharacters(in: .punctuationCharacters)
                    let isCorrected = corrections[cleanWord] != nil
                    let isSelected = selectedRange?.contains(index) ?? false

                    WordToken(
                        index: index,
                        word: word,
                        cleanWord: cleanWord,
                        isCorrected: isCorrected,
                        isSelected: isSelected,
                        corrections: corrections,
                        onTap: { tappedIndex in
                            handleWordTap(index: tappedIndex)
                        }
                    )
                    .popover(isPresented: Binding(
                        get: { showPopover && popoverAnchorIndex == index },
                        set: { newValue in
                            if !newValue {
                                showPopover = false
                                selectedRange = nil
                                pauseRefresh = false
                            }
                        }
                    ), arrowEdge: .bottom) {
                        popoverContent
                    }
                }
            }
        }
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }

    private var popoverContent: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Correct \"\(selectedPhrase)\"")
                .font(.headline)
            HStack(spacing: 8) {
                TextField("Correction", text: $correctionText)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 220)
                    .onSubmit { saveCorrection() }
                Button("Save") { saveCorrection() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
            }
            .padding(.bottom, 2)
        }
        .padding(14)
    }

    private func handleWordTap(index: Int) {
        if let existing = selectedRange {
            if existing.contains(index) && !showPopover {
                // Tapped inside selection → open popover
                openPopover(anchorIndex: index)
            } else if !showPopover {
                // Extend selection to include tapped word
                let newStart = min(existing.lowerBound, index)
                let newEnd = max(existing.upperBound, index)
                selectedRange = newStart...newEnd
            } else {
                // Popover is open, tapped outside → new selection
                showPopover = false
                selectedRange = index...index
            }
        } else {
            // No selection yet → select this word
            selectedRange = index...index
        }
    }

    private func openPopover(anchorIndex: Int) {
        let phrase = selectedPhrase
        // Check if the whole phrase has an existing correction
        correctionText = corrections[phrase] ?? phrase
        popoverAnchorIndex = anchorIndex
        showPopover = true
        pauseRefresh = true
    }

    private func saveCorrection() {
        let phrase = selectedPhrase
        onSaveCorrection(phrase, correctionText)
        showPopover = false
        selectedRange = nil
        pauseRefresh = false
    }
}

/// Simple flow layout for wrapping word buttons
struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX && x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: .unspecified)
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
