// ltrecord: пишет микрофон и системный звук в два отдельных WAV (16 кГц, моно).
// Использование: ltrecord <mic.wav> <system.wav>
// Остановка: SIGINT или SIGTERM. Требует macOS 15+ (захват микрофона в ScreenCaptureKit).
import AVFoundation
import Foundation
import ScreenCaptureKit

final class WavSink {
    private let writer: AVAssetWriter
    private let input: AVAssetWriterInput
    private var started = false
    private let lock = NSLock()

    init(path: String) throws {
        try? FileManager.default.removeItem(atPath: path)
        writer = try AVAssetWriter(outputURL: URL(fileURLWithPath: path), fileType: .wav)
        input = AVAssetWriterInput(mediaType: .audio, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ])
        input.expectsMediaDataInRealTime = true
        writer.add(input)
    }

    func append(_ sb: CMSampleBuffer) {
        guard sb.isValid, CMSampleBufferGetNumSamples(sb) > 0 else { return }
        lock.lock(); defer { lock.unlock() }
        if !started {
            guard writer.startWriting() else { return }
            writer.startSession(atSourceTime: sb.presentationTimeStamp)
            started = true
        }
        if input.isReadyForMoreMediaData { input.append(sb) }
    }

    func finish() async {
        lock.lock()
        let wasStarted = started
        lock.unlock()
        guard wasStarted else { return }
        input.markAsFinished()
        await writer.finishWriting()
    }
}

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    let mic: WavSink
    let system: WavSink
    var stream: SCStream?

    init(micPath: String, systemPath: String) throws {
        mic = try WavSink(path: micPath)
        system = try WavSink(path: systemPath)
    }

    func start() async throws {
        let content = try await SCShareableContent.current
        guard let display = content.displays.first else { throw NSError(domain: "ltrecord", code: 1, userInfo: [NSLocalizedDescriptionKey: "no display"]) }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.captureMicrophone = true
        cfg.excludesCurrentProcessAudio = true
        cfg.sampleRate = 48000
        cfg.channelCount = 1
        // Картинка не нужна: минимальный размер и редкие кадры
        cfg.width = 2
        cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let s = SCStream(filter: filter, configuration: cfg, delegate: self)
        let q = DispatchQueue(label: "ltrecord.audio")
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: q)
        try s.addStreamOutput(self, type: .microphone, sampleHandlerQueue: q)
        try s.addStreamOutput(self, type: .screen, sampleHandlerQueue: q)
        try await s.startCapture()
        stream = s
    }

    func stop() async {
        try? await stream?.stopCapture()
        await mic.finish()
        await system.finish()
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        switch type {
        case .audio: system.append(sb)
        case .microphone: mic.append(sb)
        default: break
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write(Data("stream stopped: \(error.localizedDescription)\n".utf8))
    }
}

let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: ltrecord <mic.wav> <system.wav>\n".utf8))
    exit(64)
}

var recorder: Recorder?
var sigSources: [DispatchSourceSignal] = []

Task {
    do {
        let r = try Recorder(micPath: args[1], systemPath: args[2])
        try await r.start()
        recorder = r
        print("READY")
        fflush(stdout)
    } catch {
        FileHandle.standardError.write(Data("start failed: \(error.localizedDescription)\n".utf8))
        exit(2)
    }
}

for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler {
        Task {
            await recorder?.stop()
            print("SAVED")
            fflush(stdout)
            exit(0)
        }
    }
    src.resume()
    sigSources.append(src)
}

dispatchMain()
