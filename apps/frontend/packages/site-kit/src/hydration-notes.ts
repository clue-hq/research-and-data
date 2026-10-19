// The render page's hydration notes, as the agent reads them (publishing live sites, final review F3).
// Production React minifies its errors ("Minified React error #418; visit https://react.dev/…"), and
// a code alone tells the agent nothing. The hydration codes all mean one thing to it: the server and
// the browser drew the page differently. Such a note says so in a sentence; whatever comes before the
// error ("mismatch: ", "section failed: <name>: ") is kept, and every other note is left as written.
const HYDRATION_ERROR = /Minified React error #(418|419|420|421|422|423|425)(?!\d)[\s\S]*$/;

export function hydrationNote(message: string): string {
  return message.replace(HYDRATION_ERROR, (_error, code: string) => `the server and the browser drew this page differently (React #${code})`);
}
