import { describe, expect, it } from "vitest";
import { asFortranVolume, fortranVolumeValue, projectFortranVolume, readFloat32LittleEndian } from "./matlab-artifact";

describe("MATLAB binary artifact reader", () => {
  it("reads little-endian float32 payloads", () => {
    const bytes = new Uint8Array(8);
    const view = new DataView(bytes.buffer);
    view.setFloat32(0, 0.25, true);
    view.setFloat32(4, 0.75, true);
    expect(readFloat32LittleEndian(bytes.buffer)).toEqual([0.25, 0.75]);
  });

  it("projects a Fortran ordered 3D volume by max over z", () => {
    const values = [0.1, 0.2, 0.3, 0.4, 0.9, 0.6, 0.7, 0.8];
    expect(projectFortranVolume(values, [2, 2, 2])).toEqual([
      [0.9, 0.7],
      [0.6, 0.8],
    ]);
  });

  it("preserves every voxel in a Fortran ordered 3D volume", () => {
    const volume = asFortranVolume([1, 2, 3, 4, 5, 6, 7, 8], [2, 2, 2]);
    expect(volume.shape).toEqual([2, 2, 2]);
    expect(fortranVolumeValue(volume, 0, 0, 0)).toBe(1);
    expect(fortranVolumeValue(volume, 1, 0, 0)).toBe(2);
    expect(fortranVolumeValue(volume, 0, 0, 1)).toBe(5);
  });
});
