import SwiftUI

struct HistoryEntry: Identifiable {
    let id = UUID()
    let timestamp: String
    let text: String
    let durationS: Double
    let db: Double
}

struct HistoryView: View {
    @ObservedObject var config: ConfigManager
    var onDismiss: () -> Void

    @State private var entries: [HistoryEntry] = []
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
        .onReceive(refreshTimer) { _ in loadHistory() }
    }

    private func loadHistory() {
        let historyURL = ConfigManager.configDir.appendingPathComponent("history.jsonl")
        guard let content = try? String(contentsOf: historyURL) else { return }
        let lines = content.split(separator: "\n", omittingEmptySubsequences: true)
        entries = lines.compactMap { line -> HistoryEntry? in
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
    }
}

struct WordToken: View {
    let word: String
    let cleanWord: String
    let isCorrected: Bool
    let corrections: [String: String]
    var onSave: (String, String) -> Void

    @State private var showPopover = false
    @State private var correctionText: String = ""

    var body: some View {
        Button(action: {
            correctionText = corrections[cleanWord] ?? cleanWord
            showPopover = true
        }) {
            Text(word)
                .padding(.horizontal, 5)
                .padding(.vertical, 2)
                .background(
                    isCorrected ? Color.orange.opacity(0.2) :
                    Color.secondary.opacity(0.08)
                )
                .foregroundColor(isCorrected ? .orange : .primary)
                .cornerRadius(4)
        }
        .buttonStyle(.plain)
        .popover(isPresented: $showPopover, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Correct \"\(cleanWord)\"")
                    .font(.headline)
                HStack(spacing: 8) {
                    TextField("Correction", text: $correctionText)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 180)
                        .onSubmit {
                            onSave(cleanWord, correctionText)
                            showPopover = false
                        }
                    Button("Save") {
                        onSave(cleanWord, correctionText)
                        showPopover = false
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                }
                .padding(.bottom, 2)
            }
            .padding(14)
        }
    }
}

struct EntryCard: View {
    let entry: HistoryEntry
    let corrections: [String: String]
    var onSaveCorrection: (String, String) -> Void

    private var words: [String] {
        entry.text.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Timestamp + meta
            HStack(spacing: 8) {
                Text(entry.timestamp)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text(String(format: "%.1fs", entry.durationS))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            // Words as clickable tokens — each manages its own popover
            FlowLayout(spacing: 4) {
                ForEach(Array(words.enumerated()), id: \.offset) { index, word in
                    let cleanWord = word.trimmingCharacters(in: .punctuationCharacters)
                    let isCorrected = corrections[cleanWord] != nil

                    WordToken(
                        word: word,
                        cleanWord: cleanWord,
                        isCorrected: isCorrected,
                        corrections: corrections,
                        onSave: onSaveCorrection
                    )
                }
            }
        }
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
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
