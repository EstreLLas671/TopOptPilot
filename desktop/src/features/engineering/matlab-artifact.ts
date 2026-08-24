export function readFloat32LittleEndian(buffer: ArrayBuffer): number[] {
  if (buffer.byteLength % 4 !== 0) throw new Error("Float32 artifact byte length is invalid");
  const view = new DataView(buffer);
  const values: number[] = [];
  for (let offset = 0; offset < buffer.byteLength; offset += 4) values.push(view.getFloat32(offset, true));
  if (values.some(value => !Number.isFinite(value))) throw new Error("Float32 artifact contains non-finite values");
  return values;
}

export function projectFortranVolume(values: number[], shape: number[]): number[][] {
  const [rows, columns, layers = 1] = shape.map(Number);
  if (![rows, columns, layers].every(value => Number.isInteger(value) && value > 0)) throw new Error("MATLAB artifact shape is invalid");
  if (values.length !== rows * columns * layers) throw new Error("MATLAB artifact payload does not match its shape");
  return Array.from({ length: rows }, (_, row) => Array.from({ length: columns }, (_, column) => {
    let maximum = Number.NEGATIVE_INFINITY;
    for (let layer = 0; layer < layers; layer++) maximum = Math.max(maximum, values[row + rows * column + rows * columns * layer]);
    return maximum;
  }));
}
