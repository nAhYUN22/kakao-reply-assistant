// This helper only submits through AXPress on the send button of one exact window.
// Protocol uses stdin/stdout. Names and message text never appear in argv or output.
import AppKit
import ApplicationServices
import Foundation

struct Request: Decodable {
    let target: String
    let body: String
}

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success
    else { return nil }
    return value
}

func string(_ element: AXUIElement, _ name: String) -> String? {
    attribute(element, name) as? String
}

func exactWindow(_ app: AXUIElement, _ title: String) -> AXUIElement? {
    guard let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement] else { return nil }
    let matches = windows.filter { string($0, kAXTitleAttribute) == title }
    guard matches.count == 1, string(matches[0], kAXRoleAttribute) == kAXWindowRole,
          attribute(matches[0], kAXMinimizedAttribute) as? Bool == false else { return nil }
    return matches[0]
}

func belongs(_ element: AXUIElement, to window: AXUIElement) -> Bool {
    guard let owner = attribute(element, kAXWindowAttribute) else { return false }
    return CFEqual(owner, window)
}

func controls(_ window: AXUIElement) -> (input: AXUIElement, send: AXUIElement)? {
    var pending = [window]
    var seen = Set<AXUIElement>()
    var inputs: [AXUIElement] = []
    var buttons: [AXUIElement] = []
    let skip = ["AXTable", "AXOutline", "AXList", "AXRow", "AXCell", "AXMenu"]
    let labels = ["보내기", "전송", "메시지 전송", "메시지 보내기", "Send", "Send message"]
    while let element = pending.popLast() {
        if !seen.insert(element).inserted { continue }
        guard seen.count <= 500, let role = string(element, kAXRoleAttribute) else { return nil }
        if role == "AXSheet" { return nil }
        if skip.contains(role) { continue }
        if role == kAXTextAreaRole {
            var writable = DarwinBoolean(false)
            if AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &writable) == .success,
               writable.boolValue, belongs(element, to: window) {
                inputs.append(element)
            }
        }
        if role == kAXButtonRole, belongs(element, to: window),
           [string(element, kAXTitleAttribute), string(element, kAXDescriptionAttribute)]
            .compactMap({ $0 }).contains(where: { labels.contains($0) }) {
            var actions: CFArray?
            if AXUIElementCopyActionNames(element, &actions) == .success,
               (actions as? [String])?.contains(kAXPressAction) == true { buttons.append(element) }
        }
        if let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] {
            pending.append(contentsOf: children)
        }
    }
    guard inputs.count == 1 && buttons.count == 1 else { return nil }
    return (inputs[0], buttons[0])
}

func signal(_ message: String) {
    FileHandle.standardOutput.write(Data((message + "\n").utf8))
}

func run() -> Bool {
    guard let line = readLine(), line.utf8.count < 16_384,
          let request = try? JSONDecoder().decode(Request.self, from: Data(line.utf8)),
          !request.target.isEmpty, !request.body.isEmpty, AXIsProcessTrusted() else { return false }
    let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.kakao.KakaoTalkMac")
    guard apps.count == 1 else { return false }
    let app = AXUIElementCreateApplication(apps[0].processIdentifier)
    AXUIElementSetMessagingTimeout(app, 0.5)
    guard let window = exactWindow(app, request.target), let pair = controls(window),
          string(pair.input, kAXValueAttribute) == "" else { return false }
    signal("READY")
    guard readLine() == "SUBMIT", let fresh = exactWindow(app, request.target),
          CFEqual(fresh, window), let freshPair = controls(fresh),
          CFEqual(pair.input, freshPair.input), CFEqual(pair.send, freshPair.send),
          string(pair.input, kAXValueAttribute) == "" else { return false }
    // Never replace a human draft, post global keyboard events, or retry an action.
    guard AXUIElementSetAttributeValue(pair.input, kAXValueAttribute as CFString, request.body as CFString) == .success,
          let finalWindow = exactWindow(app, request.target), CFEqual(finalWindow, window),
          belongs(pair.input, to: finalWindow), belongs(pair.send, to: finalWindow),
          string(pair.input, kAXValueAttribute) == request.body,
          attribute(pair.send, kAXEnabledAttribute) as? Bool == true,
          AXUIElementPerformAction(pair.send, kAXPressAction as CFString) == .success else { return false }
    // A new transcript occurrence is also required by the caller.
    for _ in 0..<10 {
        if string(pair.input, kAXValueAttribute) == "" { signal("SUBMITTED"); return true }
        Thread.sleep(forTimeInterval: 0.05)
    }
    return false
}

exit(run() ? 0 : 1)
