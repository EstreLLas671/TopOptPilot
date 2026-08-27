export function readFloat32LittleEndian(buffer: ArrayBuffer): number[] {
  if (buffer.byteLength % 4 !== 0) throw new Error("Float32 artifact byte length is invalid");
  const view = new DataView(buffer);
  const values: number[] = [];
  for (let offset = 0; offset < buffer.byteLength; offset += 4) values.push(view.getFloat32(offset, true));
  if (values.some(value => !Number.isFinite(value))) throw new Error("Float32 artifact contains non-finite values");
  return values;
}

export type MatlabVolume = {
  shape: [number, number, number];
  values: number[];
};

function normalizedShape(shape: number[]): [number, number, number] {
  const [rows, columns, layers = 1] = shape.map(Number);
  if (![rows, columns, layers].every(value => Number.isInteger(value) && value > 0)) {
    throw new Error("MATLAB artifact shape is invalid");
  }
  return [rows, columns, layers];
}

export function asFortranVolume(values: number[], shape: number[]): MatlabVolume {
  const normalized = normalizedShape(shape);
  if (values.length !== normalized[0] * normalized[1] * normalized[2]) {
    throw new Error("MATLAB artifact payload does not match its shape");
  }
  return { shape: normalized, values };
}

export function fortranVolumeValue(volume: MatlabVolume, row: number, column: number, layer: number): number {
  const [rows, columns, layers] = volume.shape;
  if (row < 0 || row >= rows || column < 0 || column >= columns || layer < 0 || layer >= layers) return 0;
  return volume.values[row + rows * column + rows * columns * layer];
}

export function projectFortranVolume(values: number[], shape: number[]): number[][] {
  const volume = asFortranVolume(values, shape);
  const [rows, columns, layers] = volume.shape;
  return Array.from({ length: rows }, (_, row) => Array.from({ length: columns }, (_, column) => {
    let maximum = Number.NEGATIVE_INFINITY;
    for (let layer = 0; layer < layers; layer++) maximum = Math.max(maximum, fortranVolumeValue(volume, row, column, layer));
    return maximum;
  }));
}
