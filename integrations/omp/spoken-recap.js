/**
 * omp extension: speak a one-sentence recap of each main-session response.
 *
 * Install as a user-level hook:
 *   mkdir -p ~/.omp/agent/hooks/post
 *   cp integrations/omp/spoken-recap.js ~/.omp/agent/hooks/post/
 *
 * Uses the `kokoro-tts` CLI from this repository (PATH or
 * ~/.local/bin/kokoro-tts). Tune with:
 *   KOKORO_RECAP=0             disable without removing the file
 *   KOKORO_RECAP_VOICE         voice id (default af_heart)
 *   KOKORO_RECAP_SPEED         speaking rate (default 1.0)
 *   KOKORO_TTS_BIN             explicit kokoro-tts path
 *   KOKORO_RECAP_HEADLESS=1    also speak in --print / RPC runs
 */
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MAX_CHARS = 200;
const DEFAULT_VOICE = "af_heart";
const DEFAULT_SPEED = 1.0;

function kokoroBin() {
	if (process.env.KOKORO_TTS_BIN) return process.env.KOKORO_TTS_BIN;
	const local = join(homedir(), ".local", "bin", "kokoro-tts");
	return existsSync(local) ? local : "kokoro-tts";
}

function assistantText(messages) {
	if (!Array.isArray(messages)) return "";
	for (let index = messages.length - 1; index >= 0; index--) {
		const message = messages[index];
		if (message?.role === "user") return "";
		if (message?.role !== "assistant") continue;
		if (message.stopReason === "aborted" || message.stopReason === "error") return "";
		if (!Array.isArray(message.content)) continue;
		const text = message.content
			.filter(block => block?.type === "text" && typeof block.text === "string")
			.map(block => block.text)
			.join(" ")
			.trim();
		if (text) return text;
	}
	return "";
}

function cleanLine(line) {
	return line
		.replace(/^\s*#{1,6}\s+/, "")
		.replace(/^\s*(?:[-*+•]|\d+[.)])\s+/, "")
		.replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
		.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
		.replace(/<[^>]+>/g, " ")
		.replace(/(\*\*|__)(.*?)\1/g, "$2")
		.replace(/(\*)(.*?)\1/g, "$2")
		.replace(/[\p{Extended_Pictographic}\uFE0F\u200B-\u200D]/gu, "")
		.replace(/\s+/g, " ")
		.trim();
}

function oneSentence(input) {
	const body = String(input ?? "")
		.replace(/```[\s\S]*?```/g, "\n")
		.replace(/`([^`]*)`/g, "$1");
	const sentences = [];
	for (const line of body.split(/\n+/)) {
		const cleaned = cleanLine(line);
		if (!cleaned) continue;
		for (const sentence of cleaned.split(/(?<=[.!?])\s+(?=[A-Z0-9"'([])/u)) {
			if (sentence.trim()) sentences.push(sentence.trim());
		}
	}
	if (sentences.length === 0) return "";
	const words = sentence => sentence.trim().split(/\s+/).filter(Boolean).length;
	const picked =
		sentences.find(sentence => words(sentence) >= 4 && !sentence.trim().endsWith("?")) ?? sentences[0];
	let text = picked.trim();
	if (text.length > MAX_CHARS) {
		const candidate = text.slice(0, MAX_CHARS);
		const boundary = Math.max(
			candidate.lastIndexOf(". "),
			candidate.lastIndexOf("; "),
			candidate.lastIndexOf(", "),
			candidate.lastIndexOf(" "),
		);
		text = candidate.slice(0, boundary > 60 ? boundary : MAX_CHARS).replace(/[,;:\-–—]$/, "").trim();
	}
	if (!/[.!?][)"']?$/.test(text)) text += ".";
	return text;
}

export default function spokenRecap(pi) {
	let active;
	const enabled = process.env.KOKORO_RECAP !== "0";
	const voice = process.env.KOKORO_RECAP_VOICE || DEFAULT_VOICE;
	const speed = Number.parseFloat(process.env.KOKORO_RECAP_SPEED || "");
	const speechRate = Number.isFinite(speed) && speed > 0 ? speed : DEFAULT_SPEED;

	pi.on("agent_end", async (event, ctx) => {
		if (!enabled) return;
		if (ctx.agent?.kind !== "main") return;
		if (ctx.mode !== "tui" && process.env.KOKORO_RECAP_HEADLESS !== "1") return;
		if (event.willContinue === true) return;

		const sentence = oneSentence(assistantText(event.messages));
		if (!sentence) return;

		active?.abort();
		const controller = new AbortController();
		active = controller;
		try {
			const result = await pi.exec(
				kokoroBin(),
				[sentence, "--voice", voice, "--speed", String(speechRate), "--quiet"],
				{ timeout: 27_000, signal: controller.signal },
			);
			if (result.code !== 0 && !controller.signal.aborted) {
				pi.logger?.warn?.(`spoken-recap: kokoro-tts exited ${result.code}: ${result.stderr.trim()}`);
			}
		} catch (error) {
			if (!controller.signal.aborted) {
				pi.logger?.warn?.(`spoken-recap: ${error instanceof Error ? error.message : String(error)}`);
			}
		} finally {
			if (active === controller) active = undefined;
		}
	});
}

export { assistantText, oneSentence };
