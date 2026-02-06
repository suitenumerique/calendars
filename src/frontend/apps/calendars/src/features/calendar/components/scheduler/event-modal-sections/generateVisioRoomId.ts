const randomLetters = (n: number): string =>
  Array.from({ length: n }, () =>
    String.fromCharCode(97 + Math.floor(Math.random() * 26)),
  ).join("");

export const generateVisioRoomId = (): string =>
  `${randomLetters(3)}-${randomLetters(4)}-${randomLetters(3)}`;
