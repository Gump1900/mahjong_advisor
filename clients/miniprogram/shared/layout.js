/* Resize event dimensions are authoritative while WeChat rotates its window. */
function fit(info, eventSize) {
  const width = eventSize?.windowWidth || info.windowWidth;
  const height = eventSize?.windowHeight || info.windowHeight;
  const safe = info.safeArea;
  const valid = safe && safe.left >= 0 && safe.top >= 0 && safe.right <= width && safe.bottom <= height && safe.right > safe.left && safe.bottom > safe.top;
  const area = valid ? safe : {left:width>height?36:0, right:width-(width>height?36:0), top:8, bottom:height-20};
  const usableWidth = area.right-area.left;
  const usableHeight = area.bottom-area.top;
  const scale = Math.min(usableWidth/844, usableHeight/390);
  return {scale, left:area.left+(usableWidth-844*scale)/2, top:area.top+(usableHeight-390*scale)/2};
}
module.exports = { fit };
